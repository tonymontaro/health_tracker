import asyncio
from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import MealTemplate, WeeklyMealPlan
from app.db.session import get_db
from app.main import app
from app.schemas.meal_plan import MealPlanProposal, MealPlanSelection
from app.schemas.two_week_plan import TwoWeekNutritionGuidance
from app.services.meal_planning import (
    _selection_errors,
    ensure_meal_weeks,
    serialize_meal_week,
    visible_week_starts,
)
from app.services.nutrition_regeneration import regenerate_nutrition
from app.services.planner.meal_selection import is_easy_meal
from app.services.planner.orchestrator import generate_daily_plan
from app.services.shopping import ingredient_quantity, shopping_list

MONDAY = date(2026, 8, 10)


@pytest.mark.parametrize(
    "today", [MONDAY + timedelta(days=i) for i in range(7)] + [date(2026, 12, 31)]
)
def test_calendar_always_covers_fourteen_days_and_complete_monday_weeks(today):
    starts = visible_week_starts(today)
    assert all(start.weekday() == 0 for start in starts)
    assert starts[0] <= today < starts[0] + timedelta(days=7)
    assert starts[-1] + timedelta(days=6) >= today + timedelta(days=13)
    assert len(starts) == (2 if today.weekday() == 0 else 3)


def test_weekly_recipes_stay_stable_and_daily_plan_uses_the_same_food(db, seeded, settings):
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    before = deepcopy([week.plan_json for week in weeks])
    plan = generate_daily_plan(db, settings, MONDAY, use_ai=False)
    day = before[0]["days"][0]
    nutrition = plan.current_plan_json["nutrition"]
    for index, meal in enumerate(day["meals"], 1):
        assert nutrition[f"meal_{index}"]["template_name"] == meal["template_name"]
        assert nutrition[f"meal_{index}"]["ingredients"] == meal["ingredients"]
        assert nutrition[f"meal_{index}"]["preparation"] == meal["preparation"]
        assert "multiply each listed quantity" not in meal["preparation"]
    rolled = ensure_meal_weeks(db, settings, MONDAY + timedelta(days=6), use_ai=False)
    assert len(rolled) == 3
    assert [week.plan_json for week in rolled[:2]] == before
    assert serialize_meal_week(db, weeks[0])["changed"] is False


def test_both_weeks_have_simple_weekdays_and_one_sunday_special(db, seeded, settings):
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    previous = set()
    templates = {t.name: t for t in db.scalars(select(MealTemplate))}
    for week in weeks:
        assert len(week.plan_json["days"]) == 7
        for day in week.plan_json["days"]:
            names = {meal["template_name"] for meal in day["meals"]}
            assert not previous.intersection(names)
            previous = names
            special = [meal for meal in day["meals"] if meal["special"]]
            if date.fromisoformat(day["plan_date"]).weekday() == 6:
                assert len(special) == 1
            else:
                assert not special
                assert all(is_easy_meal(templates[name]) for name in names)


def test_shopping_combines_units_and_includes_fruit_and_optional_snacks():
    ingredients = [
        ingredient_quantity({"name": "Oats", "quantity": "0.2 kg"}),
        ingredient_quantity({"name": "Eggs", "quantity": "3"}),
        ingredient_quantity({"name": "Quinoa", "quantity": "160 g cooked"}),
    ]
    days = [
        {
            "meals": [
                {"ingredients": ["oats", "eggs", "quinoa"], "shopping_ingredients": ingredients}
            ],
            "fruits": [
                {"shopping_ingredients": [{"food_name": "Apple", "quantity": 2, "unit": "item"}]}
            ],
            "snacks": [
                {
                    "shopping_ingredients": [
                        ingredient_quantity({"name": "Oats", "quantity": "40 g"})
                    ]
                }
            ],
        }
    ] * 2
    items, notes = shopping_list(days)
    quantities = {item["food_name"]: item["quantity_label"] for item in items}
    assert quantities == {
        "Oats": "480 g",
        "Eggs": "6 items",
        "Quinoa": "320 g cooked",
        "Apple": "4 items",
    }
    assert any("ready-cooked" in note for note in notes)
    with pytest.raises(ValueError):
        ingredient_quantity({"name": "Oats", "quantity": "some"})


def test_daily_regeneration_updates_calendar_and_list_preserving_originals(db, settings, seeded):
    plan = generate_daily_plan(db, settings, MONDAY, use_ai=False)
    week = db.scalar(select(WeeklyMealPlan).where(WeeklyMealPlan.week_start == MONDAY))
    original_daily = deepcopy(plan.original_plan_json)
    original_week = deepcopy(week.plan_json)
    before = serialize_meal_week(db, week)
    regenerate_nutrition(db, settings, plan, use_ai=False)
    after = serialize_meal_week(db, week)
    assert after["changed"]
    assert after["shopping"]["copy_text"] != before["shopping"]["copy_text"]
    assert (
        after["days"][0]["meals"][0]["template_name"]
        == plan.current_plan_json["nutrition"]["meal_1"]["template_name"]
    )
    assert plan.original_plan_json == original_daily
    assert week.plan_json == original_week


def test_meal_provider_validation_repairs_before_persisting_and_disables_storage(
    db, settings, seeded, monkeypatch
):
    # Use a valid fallback only to construct the provider fixture, then remove its rows.
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    days = [day for week in weeks for day in week.plan_json["days"]]
    proposal = MealPlanProposal(
        summary="AI test plan",
        days=[
            MealPlanSelection(
                plan_date=date.fromisoformat(day["plan_date"]),
                nutrition=TwoWeekNutritionGuidance(
                    expected_main_meals=len(day["meals"]),
                    meal_template_names=[m["template_name"] for m in day["meals"]],
                    focus="Simple training meals",
                    fueling_recommendations=[],
                ),
            )
            for day in days
        ],
    )
    for week in weeks:
        db.delete(week)
    db.commit()
    bad = proposal.model_copy(deep=True)
    bad.days[0].nutrition.meal_template_names[0] = "Mediterranean stuffed peppers"
    assert _selection_errors(db, seeded, bad, MONDAY, set())
    calls = []

    def parse(**kwargs):
        assert db.scalar(select(WeeklyMealPlan.id)) is None
        assert kwargs["store"] is False
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=bad if len(calls) == 1 else proposal)

    monkeypatch.setattr(
        "app.services.meal_planning.OpenAI",
        lambda **kwargs: SimpleNamespace(responses=SimpleNamespace(parse=parse)),
    )
    settings.openai_api_key = SecretStr("test-key")
    weeks = ensure_meal_weeks(db, settings, MONDAY)
    assert len(calls) == 2
    assert all(week.source == "openai" for week in weeks)
    assert weeks[0].validation_result_json["attempts"][0]["errors"]


def test_meal_endpoint_authentication_and_inventory_removal(db, settings, seeded):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings

    async def request():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/api/v1/meals/plan")).status_code == 401
            login = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": settings.bootstrap_email,
                    "password": settings.bootstrap_password.get_secret_value(),
                },
            )
            assert login.status_code == 200
            assert (await client.post("/api/v1/meals/plan")).status_code == 403
            result = await client.post(
                "/api/v1/meals/plan", headers={"X-CSRF-Token": login.json()["csrf_token"]}
            )
            assert result.status_code == 200
            assert all(len(week["days"]) == 7 for week in result.json()["weeks"])
            assert all(week["shopping"]["copy_text"] for week in result.json()["weeks"])
            assert (await client.get("/api/v1/inventory")).status_code == 404
            assert (
                await client.post("/api/v1/inventory/from-text", json={"text": "food"})
            ).status_code == 404

    try:
        asyncio.run(request())
    finally:
        app.dependency_overrides.clear()
