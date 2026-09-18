"""Deterministic titles, preferring recorded treadmill incline over the saved target."""

import re
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import StravaActivity, StravaActivityMatch, StravaConnection, WorkoutEntry

WRITE_SCOPE = "activity:write"
MAX_NAME_LENGTH = 300


def is_generic_activity_name(name: str, sport_type: str) -> bool:
    sport = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", sport_type).casefold()
    sports = {sport, sport_type.casefold(), "workout"}
    if sport_type in {"Run", "VirtualRun", "TrailRun"}:
        sports.update({"run", "treadmill run"})
    if sport_type in {"Ride", "VirtualRide", "MountainBikeRide", "GravelRide"}:
        sports.add("ride")
    normalized = " ".join(name.casefold().split())
    return any(
        normalized == f"{prefix}{activity}"
        for prefix in ("", "morning ", "afternoon ", "evening ", "night ", "lunch ")
        for activity in sports
    )


def planned_activity_entries(db: Session, activity: StravaActivity) -> list[WorkoutEntry]:
    return list(
        db.scalars(
            select(WorkoutEntry)
            .join(StravaActivityMatch, StravaActivityMatch.workout_entry_id == WorkoutEntry.id)
            .where(
                StravaActivityMatch.activity_id == activity.id,
                StravaActivityMatch.match_kind == "planned_recommendation",
                WorkoutEntry.entry_date == activity.activity_date,
                WorkoutEntry.planned_recommendation_id.is_not(None),
            )
            .order_by(WorkoutEntry.created_at, WorkoutEntry.id)
        )
    )


def recommended_activity_name(activity: StravaActivity, entries: list[WorkoutEntry]) -> str:
    if entries:
        title = " + ".join(dict.fromkeys(entry.exercise_name for entry in entries))
        targets: list[str] = []
        if len(entries) == 1:
            prescription = entries[0].prescription_json
            incline = activity.treadmill_incline_percent
            if incline is None:
                incline = prescription.get("incline_percent")
            if incline is not None:
                targets.append(f"{incline:g}% incline")
            else:
                if activity.distance_m > 0:
                    targets.append(f"{activity.distance_m / 1000:g} km")
                duration = activity.moving_time_seconds or activity.elapsed_time_seconds
                if duration > 0:
                    targets.append(f"{duration / 60:g} min")
        suffix = f" - {', '.join(targets)}" if targets else ""
        return title[: MAX_NAME_LENGTH - len(suffix)].strip() + suffix

    sport = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", activity.sport_type)
    title = (
        "Treadmill run"
        if activity.sport_type in {"Run", "VirtualRun"}
        and (activity.trainer or activity.treadmill_incline_percent is not None)
        else sport
    )
    actual: list[str] = []
    if activity.treadmill_incline_percent is not None:
        actual.append(f"{activity.treadmill_incline_percent:g}% incline")
    else:
        if activity.distance_m > 0:
            actual.append(f"{activity.distance_m / 1000:g} km")
        duration = activity.moving_time_seconds or activity.elapsed_time_seconds
        if duration > 0:
            actual.append(f"{duration / 60:g} min")
    return (f"{title} - {', '.join(actual)}" if actual else title)[:MAX_NAME_LENGTH]


def history_activity_names(db: Session, entries: list[WorkoutEntry]) -> dict[UUID, dict[str, Any]]:
    if not entries:
        return {}
    rows = db.execute(
        select(StravaActivityMatch, StravaActivity, StravaConnection)
        .join(StravaActivity, StravaActivity.id == StravaActivityMatch.activity_id)
        .join(StravaConnection, StravaConnection.id == StravaActivity.connection_id)
        .where(StravaActivityMatch.workout_entry_id.in_([entry.id for entry in entries]))
    ).all()
    by_id = {entry.id: entry for entry in entries}
    planned: dict[UUID, list[WorkoutEntry]] = defaultdict(list)
    for match, activity, _ in rows:
        entry = by_id[match.workout_entry_id]
        if (
            match.match_kind == "planned_recommendation"
            and entry.entry_date == activity.activity_date
        ):
            planned[activity.id].append(entry)
    return {
        match.workout_entry_id: {
            "activity_id": activity.strava_activity_id,
            "name": activity.name,
            "treadmill_incline_percent": activity.treadmill_incline_percent,
            "can_edit_incline": activity.sport_type in {"Run", "VirtualRun", "TrailRun"},
            "recommended_name": recommended_activity_name(
                activity,
                sorted(planned[activity.id], key=lambda entry: (entry.created_at, entry.id)),
            ),
            "can_rename": connection.status == "connected"
            and WRITE_SCOPE in connection.scopes_json,
        }
        for match, activity, connection in rows
    }
