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


def workout_line(workout: dict[str, Any]) -> str:
    if workout["kind"] == "rest":
        return "Rest"
    exercise = workout["exercises"][0]
    kind = exercise["exercise_type"]
    if kind == "run":
        return (
            f"{exercise['exercise_name']} - {exercise['distance_km']:.1f} km "
            f"@ {format_pace(exercise['pace_seconds_per_km'])}"
        )
    if kind in {"strength", "bodyweight"}:
        load = exercise.get("load_kg", exercise.get("external_load_kg", 0))
        reps = " / ".join(str(item) for item in exercise.get("reps_per_set", []))
        return f"{exercise['exercise_name']} - {load} kg - reps {reps}"
    duration = round((exercise.get("duration_seconds") or 0) / 60)
    return f"{exercise['exercise_name']} - {duration} min"


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


def morning_email(plan: dict[str, Any], app_url: str) -> tuple[str, str, str]:
    nutrition = plan["nutrition"]
    meal_lines = [f"Meal 1\n{nutrition['meal_1']['template_name']}"]
    if nutrition.get("meal_2"):
        meal_lines.append(f"Meal 2\n{nutrition['meal_2']['template_name']}")
    fruit = " · ".join(item["name"] for item in nutrition["fruits"])
    optional = " · ".join(item["name"] for item in nutrition["snacks"])
    prep = plan["prep_actions"][0]["action"] if plan["prep_actions"] else "Nothing needed"
    shopping = plan["shopping"]["summary"]
    text = f"""Current status
{plan["profile_snapshot"]["short_summary"]}

{chr(10).join(meal_lines)}

Fruit
{fruit}

Optional
{optional}

Emergency option
{emergency_plate_text()}

Training
{workout_line(plan["workout"])}

Next action
{prep}

Shopping
{shopping}

Open today's plan: {app_url}/today
"""
    html = f"""<html><body style="font-family:system-ui;line-height:1.5;color:#17332d">
<h2>Today</h2><p>{escape(plan["profile_snapshot"]["short_summary"])}</p>
<h3>Meal 1</h3><p>{escape(nutrition["meal_1"]["template_name"])}</p>
{f"<h3>Meal 2</h3><p>{escape(nutrition['meal_2']['template_name'])}</p>" if nutrition.get("meal_2") else ""}
<h3>Fruit</h3><p>{escape(fruit)}</p><h3>Optional</h3><p>{escape(optional)}</p>
<h3>Emergency option</h3>{emergency_plate_html()}
<h3>Training</h3><p>{escape(workout_line(plan["workout"]))}</p>
<h3>Next action</h3><p>{escape(prep)}</p><h3>Shopping</h3><p>{escape(shopping)}</p>
<p><a href="{escape(app_url)}/today">Open today's plan</a></p></body></html>"""
    return "Today - meals, training and next action", text, html


def evening_email(plan: dict[str, Any], app_url: str) -> tuple[str, str, str]:
    meals = plan["nutrition"]["expected_main_meals"]
    workout = workout_line(plan["workout"])
    text = f"""Planned today:
{meals} main meal{"s" if meals != 1 else ""}
{workout}

Emergency option
{emergency_plate_text()}

If anything differed, record it now.
Please also enter the workout result and difficulty.

Complete today's check-in: {app_url}/today
"""
    html = f"""<html><body style="font-family:system-ui;line-height:1.5;color:#17332d">
<h2>Quick check-in</h2><p>Planned today: {meals} main meal{"s" if meals != 1 else ""}<br>{escape(workout)}</p>
<h3>Emergency option</h3>{emergency_plate_html()}
<p>If anything differed, record it now. Please also enter workout results and difficulty.</p>
<p><a href="{escape(app_url)}/today">Complete today's check-in</a></p></body></html>"""
    return "Quick check-in for today", text, html
