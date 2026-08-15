from hashlib import sha256
from html import escape
from json import dumps
from typing import Any, Protocol

import resend

from app.core.config import Settings
from app.services.emergency_plate import EMERGENCY_PLATE


class EmailService(Protocol):
    def send(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: str,
        *,
        idempotency_key: str,
    ) -> str: ...


class ResendEmailService:
    def __init__(self, settings: Settings) -> None:
        if not settings.resend_configured:
            raise RuntimeError("Resend email requires RESEND_API_KEY, RESEND_FROM, and RESEND_TO")
        self.settings = settings
        resend.api_key = settings.resend_key_value or ""

    def send(
        self,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: str,
        *,
        idempotency_key: str,
    ) -> str:
        params: resend.Emails.SendParams = {
            "from": self.settings.resend_from or "",
            "to": [recipient],
            "subject": subject,
            "text": text_body,
            "html": html_body,
        }
        payload = dumps(params, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        payload_hash = sha256(payload.encode()).hexdigest()[:16]
        options: resend.Emails.SendOptions = {
            "idempotency_key": f"{idempotency_key}/{payload_hash}"
        }
        response = resend.Emails.send(params, options)
        message_id = response.get("id")
        if not message_id:
            raise RuntimeError("Resend returned no email identifier")
        return str(message_id)


def format_pace(seconds: int | None) -> str:
    if seconds is None:
        return ""
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}:{remainder:02d}/km"


def _number(value: Any) -> str:
    return f"{float(value):g}"


def exercise_targets(exercise: dict[str, Any]) -> str:
    kind = exercise.get("exercise_type")
    targets: list[str] = []
    if kind == "run":
        if exercise.get("distance_km") is not None:
            targets.append(f"{_number(exercise['distance_km'])} km")
        if exercise.get("pace_seconds_per_km") is not None:
            targets.append(format_pace(int(exercise["pace_seconds_per_km"])))
        if exercise.get("duration_seconds") is not None:
            targets.append(f"{round(exercise['duration_seconds'] / 60)} min")
        if exercise.get("treadmill_speed_kmh") is not None:
            targets.append(f"{_number(exercise['treadmill_speed_kmh'])} km/h")
        if exercise.get("incline_percent") is not None:
            targets.append(f"{_number(exercise['incline_percent'])}% incline")
    elif kind in {"strength", "bodyweight"}:
        load = exercise.get("load_kg")
        external_load = exercise.get("external_load_kg")
        if load is not None:
            targets.append(f"{_number(load)} kg")
        elif external_load:
            targets.append(f"bodyweight + {_number(external_load)} kg")
        else:
            targets.append("bodyweight")
        if exercise.get("sets") is not None:
            targets.append(f"{exercise['sets']} sets")
        reps = exercise.get("reps_per_set") or []
        if reps:
            targets.append("reps " + " / ".join(str(item) for item in reps))
        if exercise.get("rest_seconds") is not None:
            targets.append(f"{exercise['rest_seconds']} sec rest")
    else:
        if exercise.get("duration_seconds") is not None:
            targets.append(f"{round(exercise['duration_seconds'] / 60)} min")
        minimum_power = exercise.get("target_power_min_watts")
        maximum_power = exercise.get("target_power_max_watts")
        if minimum_power is not None and maximum_power is not None:
            targets.append(f"{minimum_power}-{maximum_power} W")
        minimum_cadence = exercise.get("cadence_min_rpm")
        maximum_cadence = exercise.get("cadence_max_rpm")
        if minimum_cadence is not None and maximum_cadence is not None:
            targets.append(f"{minimum_cadence}-{maximum_cadence} rpm")
    if exercise.get("expected_difficulty") is not None:
        targets.append(f"difficulty {exercise['expected_difficulty']}/10")
    return " - ".join(targets) or "Follow the instructions below"


def workout_line(workout: dict[str, Any]) -> str:
    if workout["kind"] == "rest":
        return "Rest"
    return "; ".join(
        f"{exercise['exercise_name']} - {exercise_targets(exercise)}"
        for exercise in workout["exercises"]
    )


def workout_text(workout: dict[str, Any]) -> str:
    if workout["kind"] == "rest":
        return f"Rest\n{workout.get('summary', 'No exercise is planned.')}"
    header = workout.get("title", "Training")
    duration = workout.get("expected_duration_minutes")
    intensity = str(workout.get("intensity", "")).replace("_", " ")
    header_details = " - ".join(
        item for item in [f"{duration} min" if duration is not None else "", intensity] if item
    )
    lines = [f"{header} - {header_details}" if header_details else header]
    if workout.get("summary"):
        lines.append(str(workout["summary"]))
    for index, exercise in enumerate(workout["exercises"], start=1):
        lines.append(f"{index}. {exercise['exercise_name']} - {exercise_targets(exercise)}")
        if exercise.get("instructions"):
            lines.append(f"   {exercise['instructions']}")
    return "\n".join(lines)


def workout_html(workout: dict[str, Any]) -> str:
    if workout["kind"] == "rest":
        return f"<p><strong>Rest</strong><br>{escape(str(workout.get('summary', 'No exercise is planned.')))}</p>"
    duration = workout.get("expected_duration_minutes")
    intensity = str(workout.get("intensity", "")).replace("_", " ")
    details = " - ".join(
        item for item in [f"{duration} min" if duration is not None else "", intensity] if item
    )
    exercises = "".join(
        "<li>"
        f"<strong>{escape(str(exercise['exercise_name']))}</strong><br>"
        f"{escape(exercise_targets(exercise))}"
        + (
            f"<br><small>{escape(str(exercise['instructions']))}</small>"
            if exercise.get("instructions")
            else ""
        )
        + "</li>"
        for exercise in workout["exercises"]
    )
    summary = f"<p>{escape(str(workout['summary']))}</p>" if workout.get("summary") else ""
    return (
        f"<p><strong>{escape(str(workout.get('title', 'Training')))}</strong>"
        f"{f' - {escape(details)}' if details else ''}</p>{summary}<ol>{exercises}</ol>"
    )


def meal_text(label: str, meal: dict[str, Any]) -> str:
    lines = [f"{label} - {meal['template_name']}"]
    if meal.get("suggested_window"):
        lines.append(f"When: {meal['suggested_window']}")
    if meal.get("description"):
        lines.append(str(meal["description"]))
    ingredients = meal.get("ingredients") or []
    if ingredients:
        lines.append("Ingredients:")
        lines.extend(f"- {ingredient}" for ingredient in ingredients)
    if meal.get("preparation"):
        lines.append(f"Preparation: {meal['preparation']}")
    facts: list[str] = []
    if meal.get("estimated_protein_g") is not None:
        facts.append(f"{_number(meal['estimated_protein_g'])} g protein")
    if meal.get("estimated_fiber_g") is not None:
        facts.append(f"{_number(meal['estimated_fiber_g'])} g fiber")
    if meal.get("hands_on_minutes") is not None:
        facts.append(f"{meal['hands_on_minutes']} active min")
    if facts:
        lines.append(" - ".join(facts))
    return "\n".join(lines)


def meal_html(label: str, meal: dict[str, Any]) -> str:
    timing = (
        f"<p><strong>When:</strong> {escape(str(meal['suggested_window']))}</p>"
        if meal.get("suggested_window")
        else ""
    )
    description = f"<p>{escape(str(meal['description']))}</p>" if meal.get("description") else ""
    ingredients = "".join(
        f"<li>{escape(str(ingredient))}</li>" for ingredient in meal.get("ingredients") or []
    )
    ingredient_list = (
        f"<p><strong>Ingredients</strong></p><ul>{ingredients}</ul>" if ingredients else ""
    )
    preparation = (
        f"<p><strong>Preparation:</strong> {escape(str(meal['preparation']))}</p>"
        if meal.get("preparation")
        else ""
    )
    facts: list[str] = []
    if meal.get("estimated_protein_g") is not None:
        facts.append(f"{_number(meal['estimated_protein_g'])} g protein")
    if meal.get("estimated_fiber_g") is not None:
        facts.append(f"{_number(meal['estimated_fiber_g'])} g fiber")
    if meal.get("hands_on_minutes") is not None:
        facts.append(f"{meal['hands_on_minutes']} active min")
    fact_line = f"<p><small>{escape(' - '.join(facts))}</small></p>" if facts else ""
    return (
        f"<h3>{escape(label)} - {escape(str(meal['template_name']))}</h3>"
        f"{timing}{description}{ingredient_list}{preparation}{fact_line}"
    )


def emergency_plate_text() -> str:
    ingredients = ", ".join(
        f"{item['quantity']} {item['name']}" for item in EMERGENCY_PLATE["ingredients"]
    )
    return (
        f"{EMERGENCY_PLATE['name']}\n"
        f"{EMERGENCY_PLATE['description']}\n"
        f"{ingredients}\n"
        f"{EMERGENCY_PLATE['estimated_protein_g']} g protein - "
        f"{EMERGENCY_PLATE['hands_on_minutes']} active minutes"
    )


def emergency_plate_html() -> str:
    ingredients = "<br>".join(
        f"{escape(str(item['quantity']))} {escape(str(item['name']))}"
        for item in EMERGENCY_PLATE["ingredients"]
    )
    return (
        '<div style="border:1px solid #d9ddd5;border-radius:12px;padding:14px;'
        'background:#f2f4ee">'
        f"<strong>{escape(str(EMERGENCY_PLATE['name']))}</strong>"
        f"<p>{escape(str(EMERGENCY_PLATE['description']))}</p>"
        f"<p>{ingredients}</p>"
        f"<small>{EMERGENCY_PLATE['estimated_protein_g']} g protein - "
        f"{EMERGENCY_PLATE['hands_on_minutes']} active minutes</small></div>"
    )


def morning_email(
    plan: dict[str, Any], app_url: str, coach_note: str | None = None
) -> tuple[str, str, str]:
    nutrition = plan["nutrition"]
    meal_sections = [meal_text("Meal 1", nutrition["meal_1"])]
    meal_html_sections = [meal_html("Meal 1", nutrition["meal_1"])]
    if nutrition.get("meal_2"):
        meal_sections.append(meal_text("Meal 2", nutrition["meal_2"]))
        meal_html_sections.append(meal_html("Meal 2", nutrition["meal_2"]))
    fruit_items = [
        " ".join(str(value) for value in [item.get("quantity"), item["name"]] if value)
        for item in nutrition["fruits"]
    ]
    fruit = "\n".join(f"- {item}" for item in fruit_items) or "None planned"
    fruit_html = "".join(f"<li>{escape(item)}</li>" for item in fruit_items)
    optional_items = [
        f"{item['name']} - {item.get('description', 'Optional')}"
        + (
            f" ({_number(item['estimated_protein_g'])} g protein)"
            if item.get("estimated_protein_g") is not None
            else ""
        )
        for item in nutrition["snacks"]
    ]
    optional = "\n".join(f"- {item}" for item in optional_items) or "None planned"
    optional_html = "".join(f"<li>{escape(item)}</li>" for item in optional_items)
    if plan["prep_actions"]:
        action = plan["prep_actions"][0]
        prep_details = [str(action["action"])]
        if action.get("when"):
            prep_details.append(str(action["when"]))
        if action.get("active_minutes") is not None:
            prep_details.append(f"{action['active_minutes']} active min")
        prep = " - ".join(prep_details)
    else:
        prep = "Nothing needed"
    shopping = plan["shopping"]["summary"]
    guidance = nutrition.get("guidance")
    text = f"""Coach Forge
{coach_note or "The plan is set. Execute it."}

Current status
{plan["profile_snapshot"]["short_summary"]}

Meals
{f"{chr(10)}{chr(10)}".join(meal_sections)}

Fruit options
{fruit}

Optional protein
{optional}
{f"{chr(10)}{chr(10)}Meal guidance{chr(10)}{guidance}" if guidance else ""}

Emergency option
{emergency_plate_text()}

Training
{workout_text(plan["workout"])}

Next action
{prep}

Shopping
{shopping}

Open today's plan: {app_url}/today
"""
    html = f"""<html><body style="font-family:system-ui;line-height:1.5;color:#17332d">
<h2>Coach Forge</h2><p><strong>{escape(coach_note or "The plan is set. Execute it.")}</strong></p>
<h2>Today</h2><p>{escape(plan["profile_snapshot"]["short_summary"])}</p>
<h2>Meals</h2>{"".join(meal_html_sections)}
<h3>Fruit options</h3>{f"<ul>{fruit_html}</ul>" if fruit_html else "<p>None planned</p>"}
<h3>Optional protein</h3>{f"<ul>{optional_html}</ul>" if optional_html else "<p>None planned</p>"}
{f"<h3>Meal guidance</h3><p>{escape(str(guidance))}</p>" if guidance else ""}
<h3>Emergency option</h3>{emergency_plate_html()}
<h2>Training</h2>{workout_html(plan["workout"])}
<h3>Next action</h3><p>{escape(prep)}</p><h3>Shopping</h3><p>{escape(shopping)}</p>
<p><a href="{escape(app_url)}/today">Open today's plan</a></p></body></html>"""
    return "Today - meals, training and next action", text, html


def evening_email(
    plan: dict[str, Any], app_url: str, coach_note: str | None = None
) -> tuple[str, str, str]:
    meals = plan["nutrition"]["expected_main_meals"]
    workout = workout_line(plan["workout"])
    text = f"""Coach Forge
{coach_note or "Close the ledger honestly."}

Planned today:
{meals} main meal{"s" if meals != 1 else ""}
{workout}

Emergency option
{emergency_plate_text()}

If anything differed, record it now.
Please also enter the workout result and difficulty.

Complete today's check-in: {app_url}/today
"""
    html = f"""<html><body style="font-family:system-ui;line-height:1.5;color:#17332d">
<h2>Coach Forge</h2><p><strong>{escape(coach_note or "Close the ledger honestly.")}</strong></p>
<h2>Quick check-in</h2><p>Planned today: {meals} main meal{"s" if meals != 1 else ""}<br>{escape(workout)}</p>
<h3>Emergency option</h3>{emergency_plate_html()}
<p>If anything differed, record it now. Please also enter workout results and difficulty.</p>
<p><a href="{escape(app_url)}/today">Complete today's check-in</a></p></body></html>"""
    return "Quick check-in for today", text, html
