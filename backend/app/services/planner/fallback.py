from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Equipment, MealTemplate, UserProfile, WorkoutEntry
from app.schemas.plan import (
    AlternativeSummary,
    DailyPlanProposal,
    ExerciseProposal,
    ExerciseType,
    FruitProposal,
    MealProposal,
    NutritionPlanProposal,
    PrepAction,
    RecommendationRationale,
    ShoppingPlanSummary,
    SnackProposal,
    WorkoutPlanProposal,
)
from app.services.planner.meal_recipes import simple_meal_recipe


def _meal(db: Session, name: str) -> MealProposal:
    template = db.scalar(select(MealTemplate).where(MealTemplate.name == name))
    if template is None:
        raise RuntimeError(f"Required fallback meal template is missing: {name}")
    return MealProposal(
        template_name=template.name,
        description=template.description,
        suggested_window="late morning to early afternoon",
        expected=True,
        estimated_protein_g=template.estimated_protein_g,
        estimated_fiber_g=template.estimated_fiber_g,
        hands_on_minutes=template.hands_on_minutes,
        ingredients=[f"{item['quantity']} {item['name']}" for item in template.ingredients_json],
        preparation=simple_meal_recipe(template),
    )


def _last_completed(db: Session, names: set[str]) -> WorkoutEntry | None:
    return db.scalar(
        select(WorkoutEntry)
        .where(
            WorkoutEntry.exercise_name.in_(names),
            WorkoutEntry.status.in_(["completed", "partial"]),
        )
        .order_by(WorkoutEntry.entry_date.desc())
    )


def _has_equipment(db: Session, name: str) -> bool:
    item = db.scalar(select(Equipment).where(Equipment.name == name))
    return bool(item and item.available)


def _run(db: Session) -> WorkoutPlanProposal:
    previous = _last_completed(db, {"Treadmill run", "Outdoor run"})
    distance = 5.0
    pace = 390
    rationale = "Conservative measurable baseline because recent running history is absent."
    if previous and previous.actual_json:
        distance = float(
            previous.actual_json.get("distance_km")
            or previous.prescription_json.get("distance_km")
            or 5
        )
        pace = int(
            previous.actual_json.get("pace_seconds_per_km")
            or (
                float(previous.actual_json["duration_seconds"])
                / float(previous.actual_json["distance_km"])
                if previous.actual_json.get("duration_seconds")
                and previous.actual_json.get("distance_km")
                else 0
            )
            or previous.prescription_json.get("pace_seconds_per_km")
            or 390
        )
        if not previous.pain_flag and (previous.difficulty_1_to_10 or 6) <= 5:
            distance = min(12, round(distance + 0.5, 1))
            rationale = "Distance increases by 0.5 km while pace remains unchanged after a comfortable session."
        elif (previous.difficulty_1_to_10 or 0) >= 8 or previous.pain_flag:
            distance = max(3, round(distance * 0.9, 1))
            rationale = "Distance is reduced after high difficulty or pain; pace is not progressed."
        else:
            rationale = "Distance and pace remain approximately unchanged from the last session."
    duration = int(round(distance * pace))
    treadmill = _has_equipment(db, "Decathlon RUN 500 treadmill")
    return WorkoutPlanProposal(
        kind="run",
        intensity="moderate",
        title="Measured aerobic run",
        exercises=[
            ExerciseProposal(
                exercise_name="Treadmill run" if treadmill else "Outdoor run",
                exercise_type=ExerciseType.RUN,
                distance_km=distance,
                pace_seconds_per_km=pace,
                duration_seconds=duration,
                treadmill_speed_kmh=round(3600 / pace, 1) if treadmill else None,
                incline_percent=0.5 if treadmill else None,
                expected_difficulty=5,
                instructions="Keep the pace even. Stop if pain changes your gait.",
            )
        ],
        expected_duration_minutes=round(duration / 60),
        summary=rationale,
    )


def _progress_reps(previous: WorkoutEntry | None, default: int) -> list[int]:
    if previous is None or previous.pain_flag:
        return [default, default, default]
    difficulty = previous.difficulty_1_to_10 or 7
    if difficulty <= 6:
        value = min(12, default + 1)
        return [value, value, value]
    if difficulty >= 9:
        value = max(4, default - 1)
        return [value, value, value]
    return [default, default, default]


def _progress_load(previous: WorkoutEntry | None, default: float, increment: float) -> float:
    if previous is None:
        return default
    actual = previous.actual_json or {}
    load = float(
        actual.get("load_kg")
        or actual.get("external_load_kg")
        or previous.prescription_json.get("load_kg")
        or previous.prescription_json.get("external_load_kg")
        or default
    )
    if previous.pain_flag:
        return load
    difficulty = previous.difficulty_1_to_10 or 7
    if difficulty <= 6:
        return load + increment
    if difficulty >= 9:
        return max(0, load - increment)
    return load


def _home_strength(db: Session) -> WorkoutPlanProposal:
    bench_previous = _last_completed(db, {"Dumbbell bench press"})
    pull_previous = _last_completed(db, {"Pull-up"})
    hinge_previous = _last_completed(db, {"Romanian deadlift"})
    available_loads = [
        load for load in (16, 20, 30) if _has_equipment(db, f"Dumbbells {load} kg pair")
    ]
    home_load = max(available_loads, default=0)
    hinge = (
        ExerciseProposal(
            exercise_name="One-arm dumbbell row",
            exercise_type=ExerciseType.STRENGTH,
            load_kg=home_load,
            sets=3,
            reps_per_set=[8, 8, 8],
            rest_seconds=120,
            expected_difficulty=6,
            instructions="This replaces the painful hinge pattern. Use controlled rows on each side.",
        )
        if hinge_previous and hinge_previous.pain_flag
        else ExerciseProposal(
            exercise_name="Romanian deadlift",
            exercise_type=ExerciseType.STRENGTH,
            load_kg=home_load,
            sets=3,
            reps_per_set=_progress_reps(hinge_previous, 8),
            rest_seconds=180,
            expected_difficulty=6,
            instructions=f"Use one {home_load} kg dumbbell per hand. Stop immediately if lower-back or waist discomfort appears.",
        )
    )
    exercises: list[ExerciseProposal] = []
    has_dumbbells = bool(available_loads)
    if has_dumbbells and _has_equipment(db, "Home gym bench"):
        exercises.append(
            ExerciseProposal(
                exercise_name="Dumbbell bench press",
                exercise_type=ExerciseType.STRENGTH,
                load_kg=home_load,
                sets=3,
                reps_per_set=_progress_reps(bench_previous, 8),
                rest_seconds=180,
                expected_difficulty=7,
                instructions=f"Use one {home_load} kg dumbbell per hand and leave one or two reps in reserve.",
            )
        )
    if _has_equipment(db, "Sportsroyals Power Tower"):
        exercises.append(
            ExerciseProposal(
                exercise_name="Pull-up",
                exercise_type=ExerciseType.BODYWEIGHT,
                external_load_kg=0,
                sets=3,
                reps_per_set=_progress_reps(pull_previous, 7),
                rest_seconds=150,
                expected_difficulty=6,
                instructions="Use strict reps and stop before form deteriorates.",
            )
        )
    if has_dumbbells:
        exercises.append(hinge)
    profile = db.scalar(select(UserProfile))
    exercises = exercises[: profile.max_exercises_per_day if profile else 3]
    if not exercises:
        return _run(db)
    return WorkoutPlanProposal(
        kind="strength",
        intensity="moderate",
        title="Home strength essentials",
        exercises=exercises,
        expected_duration_minutes=42,
        summary="Three high-value compound movements with conservative measurable targets.",
    )


def _bike(db: Session) -> WorkoutPlanProposal:
    if not _has_equipment(db, "Wahoo KICKR BIKE SHIFT"):
        return _run(db)
    return WorkoutPlanProposal(
        kind="bike",
        intensity="moderate",
        title="KICKR aerobic calibration",
        exercises=[
            ExerciseProposal(
                exercise_name="KICKR steady ride",
                exercise_type=ExerciseType.BIKE,
                duration_seconds=2400,
                cadence_min_rpm=80,
                cadence_max_rpm=90,
                expected_difficulty=5,
                instructions="Ride at a steady conversational effort. Record average power if available; no FTP is assumed.",
            )
        ],
        expected_duration_minutes=40,
        summary="A duration and cadence baseline avoids inventing an unsupported FTP.",
    )


def _gym_strength(db: Session) -> WorkoutPlanProposal:
    if not _has_equipment(db, "Commercial gym access"):
        return _run(db)
    bench_previous = _last_completed(db, {"Barbell bench press"})
    pull_previous = _last_completed(db, {"Weighted pull-up"})
    deadlift_previous = _last_completed(db, {"Deadlift"})
    deadlift = (
        ExerciseProposal(
            exercise_name="Dip",
            exercise_type=ExerciseType.BODYWEIGHT,
            external_load_kg=0,
            sets=3,
            reps_per_set=[8, 8, 8],
            rest_seconds=150,
            expected_difficulty=6,
            instructions="This replaces deadlift after a pain flag. Use a controlled range of motion.",
        )
        if deadlift_previous and deadlift_previous.pain_flag
        else ExerciseProposal(
            exercise_name="Deadlift",
            exercise_type=ExerciseType.STRENGTH,
            load_kg=_progress_load(deadlift_previous, 60, 5),
            sets=3,
            reps_per_set=[5, 5, 5],
            rest_seconds=240,
            expected_difficulty=6,
            instructions="This is a conservative calibration prescription, not a capacity claim. Stop with any lower-back or waist discomfort.",
        )
    )
    profile = db.scalar(select(UserProfile))
    exercises = [
        ExerciseProposal(
            exercise_name="Barbell bench press",
            exercise_type=ExerciseType.STRENGTH,
            load_kg=_progress_load(bench_previous, 100, 2.5),
            sets=3,
            reps_per_set=[5, 5, 5],
            rest_seconds=180,
            expected_difficulty=7,
            instructions="Use controlled repetitions and stop a set before technical failure.",
        ),
        ExerciseProposal(
            exercise_name="Weighted pull-up",
            exercise_type=ExerciseType.BODYWEIGHT,
            external_load_kg=_progress_load(pull_previous, 5, 2.5),
            sets=3,
            reps_per_set=[6, 6, 6],
            rest_seconds=180,
            expected_difficulty=7,
            instructions="Use strict range of motion. Reduce to bodyweight if needed.",
        ),
        deadlift,
    ][: profile.max_exercises_per_day if profile else 3]
    return WorkoutPlanProposal(
        kind="strength",
        intensity="moderate",
        title="Gym strength priorities",
        exercises=exercises,
        expected_duration_minutes=55,
        summary="Gym access is used for three preferred compound movements with conservative targets.",
    )


def _rest() -> WorkoutPlanProposal:
    return WorkoutPlanProposal(
        kind="rest",
        intensity="rest",
        title="Rest and commute",
        exercises=[],
        expected_duration_minutes=0,
        summary="Thursday defaults to rest because of the office day and long commute.",
    )


def build_fallback_plan(db: Session, plan_date: date) -> DailyPlanProposal:
    weekday = plan_date.strftime("%A")
    if weekday == "Thursday":
        meal_1 = _meal(db, "Thursday flexible colleague meal")
        meal_2 = None
        workout = _rest()
        prep: list[PrepAction] = []
    else:
        meal_1 = _meal(db, "Chicken power bowl")
        meal_2 = _meal(db, "Salmon potato plate")
        meal_2.suggested_window = "evening"
        workout = {
            "Monday": lambda: _home_strength(db),
            "Tuesday": lambda: _run(db),
            "Wednesday": lambda: _bike(db),
            "Friday": lambda: _run(db),
            "Saturday": lambda: _gym_strength(db),
            "Sunday": lambda: _run(db),
        }.get(weekday, lambda: _bike(db))()
        prep = (
            [PrepAction(action="Batch cook 4 chicken power bowls", active_minutes=18, when="Today")]
            if weekday in {"Sunday", "Wednesday"}
            else [
                PrepAction(
                    action="Move one prepared meal from freezer to fridge",
                    active_minutes=1,
                    when="This evening",
                )
            ]
        )

    profile = db.scalar(select(UserProfile))
    if profile and profile.max_main_meals_per_day == 1:
        meal_2 = None
    main_protein = meal_1.estimated_protein_g + (meal_2.estimated_protein_g if meal_2 else 0)
    return DailyPlanProposal(
        nutrition=NutritionPlanProposal(
            meal_1=meal_1,
            meal_2=meal_2,
            fruits=[
                FruitProposal(name="Kiwi", quantity="2", expected=False),
                FruitProposal(name="Frozen berries", quantity="150 g", expected=False),
                FruitProposal(name="Apple", quantity="1", expected=False),
            ],
            snacks=[
                SnackProposal(
                    name="Skyr / quark",
                    description="300 g with walnuts if needed to close the protein gap",
                    expected=False,
                    estimated_protein_g=36,
                ),
                SnackProposal(
                    name="Berry protein smoothie",
                    description="Optional low-effort recovery module",
                    expected=False,
                    estimated_protein_g=42,
                ),
            ],
            expected_main_meals=1 if meal_2 is None else 2,
            approximate_protein_g=min(250, main_protein + 30),
            guidance="Use one or two main meals only. Fruit and optional protein modules remain separate.",
        ),
        workout=workout,
        shopping=ShoppingPlanSummary(
            action_needed=False,
            retailer="Either",
            mode="none",
            summary="Check inventory before the next scheduled list.",
            estimated_total_chf=0,
            items=[],
        ),
        prep_actions=prep,
        short_summary="Fallback plan generated from recorded profile, schedule constraints, and recent history.",
        rationale=RecommendationRationale(
            summary="This reliable fallback prioritizes consistency, measurable training, and low active preparation time.",
            objectives=["Preserve strength", "Build aerobic consistency", "Reduce decision effort"],
            history_factors=[workout.summary],
            nutrition_factors=[
                "High-protein curated meals",
                "Produce and fiber included",
                "Optional protein module closes gaps",
            ],
            recovery_factors=["Difficulty target remains moderate", "Pain stops progression"],
            scheduling_factors=[f"{weekday} schedule rules applied"],
            progression_logic=workout.summary,
            alternatives_considered=[
                AlternativeSummary(
                    option="Rest", tradeoff="More recovery but less training stimulus"
                )
            ],
        ),
        assumptions=[
            "Inventory confidence may be incomplete",
            "Optional fruit and snacks are not assumed consumed",
        ],
    )
