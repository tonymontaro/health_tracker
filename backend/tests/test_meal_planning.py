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
from app.schemas.meal_plan import MealNutritionSelection, MealPlanProposal, MealPlanSelection
from app.services.meal_planning import (
    _selection_errors,
    ensure_meal_weeks,
    serialize_meal_periods,
    serialize_meal_week,
    shopping_period_start,
    visible_week_starts,
)
from app.services.nutrition_regeneration import regenerate_nutrition
from app.services.planner.meal_selection import is_easy_meal
from app.services.planner.orchestrator import generate_daily_plan
from app.services.shopping import ingredient_quantity, shopping_list

MONDAY = date(2026, 8, 10)


@pytest.mark.parametrize(
    "today", [MONDAY + timedelta(days=i) for i in range(28)] + [date(2026, 12, 31)]
)
def test_calendar_always_covers_fourteen_days_and_complete_monday_weeks(today):
    starts = visible_week_starts(today, MONDAY)
    assert all(start.weekday() == 0 for start in starts)
    assert starts[0] <= today < starts[0] + timedelta(days=14)
    assert starts[-1] + timedelta(days=6) >= today + timedelta(days=13)
    assert len(starts) == (2 if today == shopping_period_start(today, MONDAY) else 4)
    assert (starts[0] - MONDAY).days % 14 == 0


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
    assert len(rolled) == 4
    assert [week.plan_json for week in rolled[:2]] == before
    assert serialize_meal_week(db, weeks[0])["changed"] is False


def test_both_weeks_have_simple_weekdays_and_one_sunday_special(db, seeded, settings):
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    previous = set()
    templates = {t.name: t for t in db.scalars(select(MealTemplate))}
    for week in weeks:
        assert len(week.plan_json["days"]) == 7
        for day in week.plan_json["days"]:
            assert [meal["expected"] for meal in day["meals"]] == [True, False]
            names = {meal["template_name"] for meal in day["meals"]}
            assert not previous.intersection(names)
            previous = names
            special = [meal for meal in day["meals"] if meal["special"]]
            if date.fromisoformat(day["plan_date"]).weekday() == 6:
                assert len(special) == 1
                assert day["meals"][0]["special"]
                assert is_easy_meal(templates[day["meals"][1]["template_name"]])
            else:
                assert not special
                assert all(is_easy_meal(templates[name]) for name in names)


def test_shopping_includes_main_meals_fruit_snacks_and_nuts_but_excludes_optional_meals():
    ingredients = [
        ingredient_quantity({"name": "Oats", "quantity": "0.2 kg"}),
        ingredient_quantity({"name": "Eggs", "quantity": "3"}),
        ingredient_quantity({"name": "Quinoa", "quantity": "160 g cooked"}),
    ]
    days = [
        {
            "meals": [
                {
                    "expected": True,
                    "ingredients": ["oats", "eggs", "quinoa"],
                    "shopping_ingredients": ingredients,
                },
                {
                    "expected": False,
                    "ingredients": ["oats", "eggs", "quinoa"],
                    "shopping_ingredients": [*ingredients, {"note": "optional-only ingredient"}],
                },
            ],
            "fruits": [
                {"shopping_ingredients": [{"food_name": "Apple", "quantity": 2, "unit": "item"}]}
            ],
            "snacks": [
                {
                    "shopping_ingredients": [
                        ingredient_quantity({"name": "Oats", "quantity": "40 g"}),
                        ingredient_quantity({"name": "Walnuts / mixed nuts", "quantity": "20 g"}),
                    ]
                }
            ],
        }
    ] * 2
    items, notes = shopping_list(days)
    quantities = {item["food_name"]: item["quantity_label"] for item in items}
    assert quantities == {
        "Oats": "480 g",
        "Apple": "4 items",
        "Walnuts / mixed nuts": "40 g",
        "Eggs": "6 items",
        "Quinoa": "320 g cooked",
    }
    assert any("ready-cooked" in note for note in notes)
    assert not any("optional-only" in note for note in notes)
    with pytest.raises(ValueError):
        ingredient_quantity({"name": "Oats", "quantity": "some"})


def test_daily_regeneration_updates_calendar_and_list_preserving_originals(db, settings, seeded):
    plan = generate_daily_plan(db, settings, MONDAY, use_ai=False)
    week = db.scalar(select(WeeklyMealPlan).where(WeeklyMealPlan.week_start == MONDAY))
    original_daily = deepcopy(plan.original_plan_json)
    original_week = deepcopy(week.plan_json)
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    before = serialize_meal_periods(db, weeks)[0]
    regenerate_nutrition(db, settings, plan, use_ai=False)
    after = serialize_meal_periods(db, weeks)[0]
    assert after["changed"]
    assert after["shopping"]["copy_text"] != before["shopping"]["copy_text"]
    assert (
        after["weeks"][0]["days"][0]["meals"][0]["template_name"]
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
                nutrition=MealNutritionSelection(
                    main_meal_template_name=day["meals"][0]["template_name"],
                    optional_meal_template_name=day["meals"][1]["template_name"],
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
    bad.days[0].nutrition.main_meal_template_name = "Mediterranean stuffed peppers"
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
            periods = result.json()["periods"]
            assert all(len(period["weeks"]) == 2 for period in periods)
            assert all(len(week["days"]) == 7 for p in periods for week in p["weeks"])
            assert all(p["shopping"]["copy_text"] for p in periods)
            assert all("shopping" not in week for p in periods for week in p["weeks"])
            assert (await client.get("/api/v1/inventory")).status_code == 404
            assert (
                await client.post("/api/v1/inventory/from-text", json={"text": "food"})
            ).status_code == 404

    try:
        asyncio.run(request())
    finally:
        app.dependency_overrides.clear()


def test_order_stays_fixed_through_second_monday_and_rolls_after_fourteen_days(
    db, seeded, settings
):
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    original = serialize_meal_periods(db, weeks)[0]
    for offset in (1, 7, 13):
        visible = ensure_meal_weeks(db, settings, MONDAY + timedelta(days=offset), use_ai=False)
        periods = serialize_meal_periods(db, visible)
        assert periods[0] == original
        assert periods[1]["start_date"] == (MONDAY + timedelta(days=14)).isoformat()
    next_weeks = ensure_meal_weeks(db, settings, MONDAY + timedelta(days=14), use_ai=False)
    assert next_weeks[0].week_start == MONDAY + timedelta(days=14)
    assert len(next_weeks) == 2


def test_one_main_meal_profile_still_gets_a_distinct_optional_recipe_every_day(
    db, seeded, settings
):
    seeded.max_main_meals_per_day = 1
    seeded.preferred_main_meals_per_day = 1
    db.flush()
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    assert all(
        [m["expected"] for m in day["meals"]] == [True, False]
        for week in weeks
        for day in week.plan_json["days"]
    )
    daily = generate_daily_plan(db, settings, MONDAY, use_ai=False)
    assert daily.current_plan_json["nutrition"]["expected_main_meals"] == 1


def test_changing_only_optional_recipe_does_not_change_order(db, seeded, settings):
    from app.services.history import replace_recommendation

    plan = generate_daily_plan(db, settings, MONDAY, use_ai=False)
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    before = serialize_meal_periods(db, weeks)[0]
    optional = plan.current_plan_json["nutrition"]["meal_2"]
    replace_recommendation(
        db,
        plan,
        optional["recommendation_id"],
        {"ingredients": ["999 g optional-only ingredient"], "expected": True},
        "Optional meal adjustment",
        "user",
    )
    after = serialize_meal_periods(db, weeks)[0]
    assert after["shopping"] == before["shopping"]
    assert not after["changed"]
    assert not plan.current_plan_json["nutrition"]["meal_2"]["expected"]
    assert after["weeks"][0]["days"][0]["meals"][1]["ingredients"] == [
        "999 g optional-only ingredient"
    ]


def test_legacy_weeks_gain_optional_roles_without_replacing_saved_recipes(db, seeded, settings):
    from app.services.meal_planning import scheduled_nutrition

    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    legacy = deepcopy(weeks[0].plan_json)
    for day in legacy["days"]:
        for meal in day["meals"]:
            meal["expected"] = True
    legacy["days"][3]["meals"] = legacy["days"][3]["meals"][:1]
    weeks[0].plan_json = legacy
    db.commit()
    serialized = serialize_meal_periods(db, weeks)[0]
    assert all(
        [m["expected"] for m in day["meals"]] == [True, False]
        for week in serialized["weeks"]
        for day in week["days"]
    )
    thursday = scheduled_nutrition(db, MONDAY + timedelta(days=3))
    assert thursday and thursday.meal_2 and not thursday.meal_2.expected
    assert thursday.meal_1.template_name == legacy["days"][3]["meals"][0]["template_name"]
    assert weeks[0].plan_json == legacy


def test_active_legacy_plan_upgrade_is_audited_and_preserves_history_and_actuals(
    db, seeded, settings
):
    from app.db.models import NutritionEntry, PlanModification
    from app.services.meal_planning import apply_current_meal_roles

    historical = generate_daily_plan(db, settings, MONDAY, use_ai=False)
    today = MONDAY + timedelta(days=1)
    active = generate_daily_plan(db, settings, today, use_ai=False)
    for plan in (historical, active):
        legacy = deepcopy(plan.current_plan_json)
        legacy["nutrition"]["meal_2"]["expected"] = True
        legacy["nutrition"]["expected_main_meals"] = 2
        plan.original_plan_json = deepcopy(legacy)
        plan.current_plan_json = legacy
    optional = db.scalar(
        select(NutritionEntry).where(
            NutritionEntry.entry_date == today, NutritionEntry.meal_slot == "meal_2"
        )
    )
    optional.expected = True
    optional.status = "confirmed"
    optional.source = "history_correction"
    actual_quantity = deepcopy(optional.quantity_json)
    db.commit()
    original_active = deepcopy(active.original_plan_json)
    original_history = deepcopy(historical.current_plan_json)
    apply_current_meal_roles(db, today)
    assert active.current_plan_json["nutrition"]["expected_main_meals"] == 1
    assert active.current_plan_json["nutrition"]["meal_2"]["expected"] is False
    assert optional.expected is False
    assert optional.status == "confirmed" and optional.source == "history_correction"
    assert optional.quantity_json == actual_quantity
    assert active.original_plan_json == original_active
    assert historical.current_plan_json == historical.original_plan_json == original_history
    audits = list(db.scalars(select(PlanModification)))
    assert len(audits) == 1 and audits[0].source == "meal_policy_update"
    apply_current_meal_roles(db, today)
    assert len(list(db.scalars(select(PlanModification)))) == 1


def test_optional_meal_is_recordable_but_not_required_for_adherence(db, seeded, settings):
    from app.db.models import NutritionEntry
    from app.services.history import reconcile_day
    from app.services.metrics import calculate_nutrition_summary

    generate_daily_plan(db, settings, MONDAY, use_ai=False)
    main = db.scalar(
        select(NutritionEntry).where(
            NutritionEntry.entry_date == MONDAY, NutritionEntry.meal_slot == "meal_1"
        )
    )
    optional = db.scalar(
        select(NutritionEntry).where(
            NutritionEntry.entry_date == MONDAY, NutritionEntry.meal_slot == "meal_2"
        )
    )
    main.status = "confirmed"
    db.commit()
    result = reconcile_day(db, MONDAY)
    assert result["assumed_skipped_meals"] == 0
    assert optional.status == "planned"
    summary = calculate_nutrition_summary(db, MONDAY)
    assert summary["main_meals_planned_14d"] == 1
    assert summary["adherence_rate_14d"] == 1
    optional.status = "confirmed"
    db.commit()
    assert calculate_nutrition_summary(db, MONDAY)["adherence_rate_14d"] == 1


def test_completing_partial_period_preserves_saved_week_and_its_boundary_meals(
    db, seeded, settings
):
    weeks = ensure_meal_weeks(db, settings, MONDAY + timedelta(days=1), use_ai=False)
    saved = deepcopy(weeks[2].plan_json)
    saved["days"][-1]["meals"] = deepcopy(weeks[3].plan_json["days"][0]["meals"])
    weeks[2].plan_json = saved
    db.delete(weeks[3])
    db.commit()
    filled = ensure_meal_weeks(db, settings, MONDAY + timedelta(days=2), use_ai=False)
    assert filled[2].plan_json == saved
    sunday = {m["template_name"] for m in saved["days"][-1]["meals"]}
    next_monday = {m["template_name"] for m in filled[3].plan_json["days"][0]["meals"]}
    assert not sunday.intersection(next_monday)


def test_daily_plan_keeps_fruit_snack_and_nut_shopping_quantities_stable(db, seeded, settings):
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    before = serialize_meal_periods(db, weeks)[0]
    assert all(
        any(snack["name"] == "Walnuts / mixed nuts" for snack in day["snacks"])
        for week in before["weeks"]
        for day in week["days"]
    )
    plan = generate_daily_plan(db, settings, MONDAY, use_ai=False)
    after = serialize_meal_periods(db, weeks)[0]
    assert after["shopping"] == before["shopping"]
    assert after["changed"] is False
    assert all(not snack["expected"] for snack in plan.current_plan_json["nutrition"]["snacks"])
    assert {snack["name"] for snack in plan.current_plan_json["nutrition"]["snacks"]} == {
        "Skyr / quark",
        "Walnuts / mixed nuts",
    }


def test_extra_quantity_changes_update_the_order_without_losing_other_extras(db, seeded, settings):
    from app.services.history import replace_recommendation

    plan = generate_daily_plan(db, settings, MONDAY, use_ai=False)
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    before = serialize_meal_periods(db, weeks)[0]
    snack = next(
        s for s in plan.current_plan_json["nutrition"]["snacks"] if s["name"] == "Skyr / quark"
    )
    replace_recommendation(
        db,
        plan,
        snack["recommendation_id"],
        {"description": "300 g, according to appetite"},
        "Larger snack",
        "user",
    )
    after = serialize_meal_periods(db, weeks)[0]
    before_quantities = {i["food_name"]: i["quantity"] for i in before["shopping"]["items"]}
    after_quantities = {i["food_name"]: i["quantity"] for i in after["shopping"]["items"]}
    before_quantities["Skyr / quark"] += 100
    assert after_quantities == before_quantities
    assert after["changed"] is True


@pytest.mark.parametrize("allergy", ["nuts", "tree nuts", "almonds", "peanuts", "cashews"])
def test_default_nut_snack_respects_allergies(db, seeded, allergy):
    from app.services.meal_planning import _nut_snack

    seeded.allergies = [allergy]
    assert _nut_snack(db, seeded) is None


def test_legacy_plans_gain_nuts_once_and_keep_the_order_stable(db, seeded, settings):
    from app.db.models import NutritionEntry, PlanModification
    from app.services.meal_planning import apply_current_meal_roles

    plan = generate_daily_plan(db, settings, MONDAY, use_ai=False)
    weeks = ensure_meal_weeks(db, settings, MONDAY, use_ai=False)
    nut_name = "Walnuts / mixed nuts"
    # Reconstruct the prior format: a fruit suggestion and a protein snack, without nuts.
    for week in weeks:
        payload = deepcopy(week.plan_json)
        for day in payload["days"]:
            day["snacks"] = [s for s in day["snacks"] if s["name"] != nut_name]
        week.plan_json = payload
    old_daily = deepcopy(plan.current_plan_json)
    old_daily["nutrition"]["snacks"] = [
        s for s in old_daily["nutrition"]["snacks"] if s["name"] != nut_name
    ]
    plan.original_plan_json = deepcopy(old_daily)
    plan.current_plan_json = deepcopy(old_daily)
    entry = db.scalar(
        select(NutritionEntry).where(
            NutritionEntry.entry_date == MONDAY,
            NutritionEntry.meal_slot == "snack",
            NutritionEntry.food_or_meal_reference == nut_name,
        )
    )
    db.delete(entry)
    db.commit()
    before = serialize_meal_periods(db, weeks)[0]["shopping"]
    assert any(item["food_name"] == nut_name for item in before["items"])
    apply_current_meal_roles(db, MONDAY)
    apply_current_meal_roles(db, MONDAY)
    assert plan.original_plan_json == old_daily
    assert sum(s["name"] == nut_name for s in plan.current_plan_json["nutrition"]["snacks"]) == 1
    assert len(list(db.scalars(select(PlanModification)))) == 1
    assert serialize_meal_periods(db, weeks)[0]["shopping"] == before


def test_unparseable_extra_quantity_is_visible_for_manual_review(db, seeded):
    from app.services.shopping import shopping_ingredients_for_extra

    extras = shopping_ingredients_for_extra(
        db, {"name": "Example snack", "description": "a handful"}
    )
    _, notes = shopping_list(
        [{"meals": [], "fruits": [], "snacks": [{"shopping_ingredients": extras}]}]
    )
    assert "Check recipe quantity: Example snack: a handful" in notes
