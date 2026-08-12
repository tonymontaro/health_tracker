import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import UserProfile
from app.db.session import SessionLocal
from app.jobs.scheduler import run_scheduler
from app.jobs.tasks import (
    finalize_day,
    generate_morning_plan,
    generate_shopping,
    send_evening_checkin,
    send_morning_email,
)
from app.services.catalog import seed_all
from app.services.garmin_import import import_garmin_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="health-autopilot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("seed")
    plan = subparsers.add_parser("plan")
    plan.add_argument("--date", default=date.today().isoformat())
    plan.add_argument("--no-ai", action="store_true")
    job = subparsers.add_parser("job")
    job.add_argument(
        "name",
        choices=["morning-plan", "morning-email", "evening-email", "finalize", "shopping"],
    )
    job.add_argument("--date", default=date.today().isoformat())
    job.add_argument("--no-ai", action="store_true")
    subparsers.add_parser("scheduler")
    garmin = subparsers.add_parser("import-garmin")
    garmin.add_argument("--file", required=True, type=Path)
    goal = subparsers.add_parser("set-goal")
    goal.add_argument("--text", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    if args.command == "scheduler":
        run_scheduler()
        return
    with SessionLocal() as db:
        if args.command == "seed":
            profile = seed_all(db, settings)
            print(json.dumps({"profile_id": str(profile.id), "status": "seeded"}))
            return
        if args.command == "import-garmin":
            print(json.dumps(import_garmin_csv(db, args.file)))
            return
        if args.command == "set-goal":
            target_profile = db.scalar(select(UserProfile))
            if target_profile is None:
                raise RuntimeError("Profile must be seeded before setting a goal")
            target_profile.current_target_goal = args.text.strip() or None
            db.commit()
            print(json.dumps({"status": "saved"}))
            return
        target = date.fromisoformat(args.date)
        if args.command == "plan":
            plan = generate_morning_plan(db, settings, target, use_ai=not args.no_ai)
            print(json.dumps({"date": args.date, "source": plan.current_plan_json["source"]}))
            return
        result: object
        if args.name == "morning-plan":
            result = generate_morning_plan(
                db, settings, target, use_ai=not args.no_ai
            ).current_plan_json
        elif args.name == "morning-email":
            result = {"event_id": str(send_morning_email(db, settings, target).id)}
        elif args.name == "evening-email":
            result = {"event_id": str(send_evening_checkin(db, settings, target).id)}
        elif args.name == "finalize":
            result = finalize_day(db, target)
        else:
            result = {"plan_id": str(generate_shopping(db, settings, target).id)}
        print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
