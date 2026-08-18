from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import ProfileSnapshot, TwoWeekPlan, UserProfile
from app.schemas.two_week_plan import TwoWeekPlanDocument, TwoWeekPlanProposal
from app.services.planner.context import build_planner_context, build_profile_snapshot
from app.services.planner.domain import validate_two_week_plan
from app.services.planner.openai_planner import PlannerProviderError
from app.services.planner.openai_two_week_planner import (
    TWO_WEEK_PLANNER_VERSION,
    OpenAITwoWeekPlanner,
)
from app.services.planner.two_week_fallback import build_fallback_two_week_plan


def serialize_committed_outlook(plan: TwoWeekPlan) -> dict[str, Any]:
    return {
        "anchor_date": plan.anchor_date.isoformat(),
        "revision": plan.revision,
        "source": plan.source,
        "summary": plan.plan_json["summary"],
        "training_strategy": plan.plan_json["training_strategy"],
        "nutrition_strategy": plan.plan_json["nutrition_strategy"],
        "adjustment_summary": plan.plan_json["adjustment_summary"],
        "days": plan.plan_json["days"][:7],
        "generated_at": plan.created_at.isoformat(),
    }


def latest_two_week_plan(db: Session, anchor_date: date) -> TwoWeekPlan | None:
    return db.scalar(
        select(TwoWeekPlan)
        .where(TwoWeekPlan.anchor_date == anchor_date)
        .order_by(TwoWeekPlan.revision.desc())
    )


def ensure_two_week_plan(
    db: Session,
    settings: Settings,
    anchor_date: date,
    *,
    use_ai: bool = True,
    profile: UserProfile | None = None,
    snapshot: ProfileSnapshot | None = None,
) -> TwoWeekPlan:
    existing = latest_two_week_plan(db, anchor_date)
    if existing is not None:
        return existing
    profile = profile or db.scalar(select(UserProfile))
    if profile is None:
        raise RuntimeError("Profile has not been seeded")
    snapshot = snapshot or build_profile_snapshot(db, profile, anchor_date)
    previous = db.scalar(
        select(TwoWeekPlan)
        .where(TwoWeekPlan.anchor_date < anchor_date)
        .order_by(TwoWeekPlan.anchor_date.desc(), TwoWeekPlan.revision.desc())
    )
    return _generate_two_week_plan(
        db,
        settings,
        anchor_date,
        profile=profile,
        snapshot=snapshot,
        previous=previous,
        revision=1,
        use_ai=use_ai,
        regeneration_preference=None,
    )


def regenerate_two_week_plan(
    db: Session,
    settings: Settings,
    anchor_date: date,
    *,
    preference: str | None = None,
    use_ai: bool = True,
) -> TwoWeekPlan:
    profile = db.scalar(select(UserProfile))
    if profile is None:
        raise RuntimeError("Profile has not been seeded")
    previous = latest_two_week_plan(db, anchor_date)
    if previous is None:
        previous = db.scalar(
            select(TwoWeekPlan)
            .where(TwoWeekPlan.anchor_date < anchor_date)
            .order_by(TwoWeekPlan.anchor_date.desc(), TwoWeekPlan.revision.desc())
        )
    snapshot = build_profile_snapshot(db, profile, anchor_date)
    return _generate_two_week_plan(
        db,
        settings,
        anchor_date,
        profile=profile,
        snapshot=snapshot,
        previous=previous,
        revision=(previous.revision + 1 if previous and previous.anchor_date == anchor_date else 1),
        use_ai=use_ai,
        regeneration_preference=preference,
    )


def _generate_two_week_plan(
    db: Session,
    settings: Settings,
    anchor_date: date,
    *,
    profile: UserProfile,
    snapshot: ProfileSnapshot,
    previous: TwoWeekPlan | None,
    revision: int,
    use_ai: bool,
    regeneration_preference: str | None,
) -> TwoWeekPlan:
    daily_context = build_planner_context(
        db,
        profile,
        snapshot,
        anchor_date,
        include_two_week_plan=False,
    )
    context = {
        "planning_window": {
            "anchor_date": anchor_date.isoformat(),
            "window_start": anchor_date.isoformat(),
            "window_end": (anchor_date + timedelta(days=13)).isoformat(),
            "adaptive_dates": [
                anchor_date.isoformat(),
                (anchor_date + timedelta(days=1)).isoformat(),
            ],
            "committed_user_facing_dates": [
                (anchor_date + timedelta(days=offset)).isoformat() for offset in range(7)
            ],
            "provisional_dates": [
                (anchor_date + timedelta(days=offset)).isoformat() for offset in range(7, 14)
            ],
        },
        "current_evidence_and_constraints": daily_context,
        "previous_plan": previous.plan_json if previous is not None else None,
        "manual_regeneration": {
            "requested": revision > 1 or regeneration_preference is not None,
            "user_preference": regeneration_preference,
            "instruction": (
                "Create a materially refreshed but safe horizon. Treat the optional preference as "
                "high priority after all hard constraints."
            ),
        },
        "stability_policy": {
            "adaptive_days": "Change responsively when recorded evidence warrants it.",
            "remaining_committed_days": (
                "Preserve overlapping dates unless safety, recovery, or schedule evidence "
                "provides a clear reason to change."
            ),
            "provisional_days": "Rebalance as needed to protect the full horizon.",
        },
    }

    proposal = None
    source: Literal["openai", "fallback"] = "fallback"
    validation: dict[str, Any] = {"attempts": []}
    if use_ai and settings.openai_key_value:
        planner = OpenAITwoWeekPlanner(settings)
        correction: dict[str, Any] | None = None
        last_error: str | None = None
        for attempt in (1, 2):
            try:
                candidate = planner.generate(context, correction=correction)
            except PlannerProviderError as exc:
                last_error = str(exc)
                validation["attempts"].append(
                    {"attempt": attempt, "errors": [last_error], "stage": "provider"}
                )
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {str(exc)[:1500]}"
                validation["attempts"].append(
                    {"attempt": attempt, "errors": [last_error], "stage": "schema_or_provider"}
                )
                correction = {
                    "errors": [last_error],
                    "instruction": "Return a fresh response satisfying every schema constraint.",
                }
                continue
            errors = validate_two_week_plan(db, candidate, profile, anchor_date)
            errors.extend(_manual_regeneration_errors(candidate, previous, anchor_date, revision))
            validation["attempts"].append({"attempt": attempt, "errors": errors, "stage": "domain"})
            if not errors:
                proposal = candidate
                source = "openai"
                break
            last_error = "; ".join(errors)
            correction = {
                "errors": errors,
                "invalid_candidate": candidate.model_dump(mode="json"),
            }
        if proposal is None and last_error:
            validation["openai_error"] = last_error

    if proposal is None:
        proposal = build_fallback_two_week_plan(
            db,
            profile,
            anchor_date,
            previous,
            preserve_previous=revision == 1,
            variation_seed=revision - 1,
        )
        fallback_errors = validate_two_week_plan(db, proposal, profile, anchor_date)
        fallback_errors.extend(
            _manual_regeneration_errors(proposal, previous, anchor_date, revision)
        )
        validation["fallback_errors"] = fallback_errors
        if fallback_errors:
            raise RuntimeError(f"Deterministic two-week fallback is invalid: {fallback_errors}")

    document = TwoWeekPlanDocument(
        **proposal.model_dump(),
        anchor_date=anchor_date,
        source=source,
    )
    row = TwoWeekPlan(
        anchor_date=anchor_date,
        revision=revision,
        window_start=document.window_start,
        window_end=document.window_end,
        previous_plan_id=previous.id if previous is not None else None,
        profile_snapshot_id=snapshot.id,
        model=settings.openai_planner_model if source == "openai" else "deterministic-fallback",
        planner_version=TWO_WEEK_PLANNER_VERSION,
        source=source,
        context_snapshot_json=context,
        plan_json=document.model_dump(mode="json"),
        validation_result_json=validation,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _manual_regeneration_errors(
    proposal: TwoWeekPlanProposal,
    previous: TwoWeekPlan | None,
    anchor_date: date,
    revision: int,
) -> list[str]:
    if revision <= 1 or previous is None or previous.anchor_date != anchor_date:
        return []
    prior_document = TwoWeekPlanDocument.model_validate(previous.plan_json)
    prior_today = prior_document.days[0]
    candidate_today = proposal.days[0]
    errors: list[str] = []
    if candidate_today.workout != prior_today.workout:
        errors.append("Manual weekly regeneration must preserve today's workout guidance.")
    if candidate_today.nutrition != prior_today.nutrition:
        errors.append("Manual weekly regeneration must preserve today's nutrition guidance.")
    return errors
