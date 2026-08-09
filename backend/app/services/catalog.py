from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password, token_digest
from app.db.models import (
    ApiToken,
    Equipment,
    Exercise,
    FoodItem,
    MealTemplate,
    UserAccount,
    UserProfile,
)

PRIMARY_GOAL = (
    "Become a very strong hybrid athlete who retains substantial strength while comfortably "
    "running 8-12 km and developing strong general aerobic fitness."
)


EQUIPMENT = [
    ("Wahoo KICKR BIKE SHIFT", "exercise", {"type": "indoor_bike"}),
    ("Decathlon RUN 500 treadmill", "exercise", {"type": "treadmill"}),
    ("Home gym bench", "exercise", {}),
    ("Dumbbells 16 kg pair", "exercise", {"load_kg_each": 16}),
    ("Dumbbells 20 kg pair", "exercise", {"load_kg_each": 20}),
    ("Dumbbells 30 kg pair", "exercise", {"load_kg_each": 30}),
    ("Sportsroyals Power Tower", "exercise", {"supports": ["pull-up", "dip", "push-up"]}),
    ("Commercial gym access", "exercise", {"days": ["Saturday", "Sunday"]}),
    ("High-quality blender", "kitchen", {}),
]


EXERCISES = [
    ("Barbell bench press", "strength", ["barbell", "bench"], True, True, "load_reps"),
    ("Dumbbell bench press", "strength", ["dumbbells", "bench"], False, True, "load_reps"),
    ("Deadlift", "strength", ["barbell"], True, True, "load_reps"),
    ("Romanian deadlift", "strength", ["dumbbells"], False, True, "load_reps"),
    ("Pull-up", "bodyweight", ["power tower"], False, True, "reps"),
    ("Weighted pull-up", "bodyweight", ["pull-up bar", "weights"], True, True, "load_reps"),
    ("Dip", "bodyweight", ["power tower"], False, True, "reps"),
    ("Weighted dip", "bodyweight", ["dip bars", "weights"], True, True, "load_reps"),
    ("One-arm dumbbell row", "strength", ["dumbbell"], False, True, "load_reps"),
    ("Barbell row", "strength", ["barbell"], True, True, "load_reps"),
    ("Overhead press", "strength", ["barbell"], True, True, "load_reps"),
    ("Treadmill run", "run", ["treadmill"], False, True, "distance_pace"),
    ("Outdoor run", "run", [], False, True, "distance_pace"),
    ("KICKR steady ride", "bike", ["KICKR bike"], False, True, "duration_power"),
    ("KICKR interval ride", "bike", ["KICKR bike"], False, True, "intervals"),
    ("Walking / easy movement", "recovery", [], False, False, "duration"),
    ("Optional mobility", "recovery", [], False, False, "duration"),
]


FOODS: list[tuple[str, str, float, float, float, float, float, str, int | None, bool]] = [
    ("Chicken breast", "protein", 31, 0, 3.6, 0, 165, "g", 3, True),
    ("Salmon", "protein", 20, 0, 13, 0, 208, "g", 2, True),
    ("Sardines", "protein", 25, 0, 11, 0, 208, "g", 365, False),
    ("Eggs", "protein", 13, 1.1, 11, 0, 155, "g", 28, False),
    ("Skyr / quark", "protein", 11, 4, 0.2, 0, 63, "g", 14, False),
    ("Cottage cheese", "protein", 12, 3.4, 4.3, 0, 98, "g", 10, False),
    ("Lentils", "legume", 9, 20, 0.4, 8, 116, "g cooked", 4, True),
    ("Chickpeas", "legume", 9, 27, 2.6, 8, 164, "g cooked", 4, True),
    ("Oats", "carbohydrate", 17, 66, 7, 11, 389, "g", 365, False),
    ("Potatoes", "carbohydrate", 2, 17, 0.1, 2.2, 77, "g", 21, False),
    ("Brown rice", "carbohydrate", 2.6, 23, 0.9, 1.6, 123, "g cooked", 4, True),
    ("Quinoa", "carbohydrate", 4.4, 21, 1.9, 2.8, 120, "g cooked", 4, True),
    ("Wholegrain bread", "carbohydrate", 13, 41, 4.2, 7, 247, "g", 5, True),
    ("Broccoli", "vegetable", 2.8, 7, 0.4, 2.6, 34, "g", 5, True),
    ("Spinach", "vegetable", 2.9, 3.6, 0.4, 2.2, 23, "g", 4, True),
    ("Peppers", "vegetable", 1, 6, 0.3, 2.1, 31, "g", 7, True),
    ("Tomatoes", "vegetable", 0.9, 3.9, 0.2, 1.2, 18, "g", 7, False),
    ("Frozen mixed vegetables", "vegetable", 3, 8, 0.5, 3, 50, "g", 180, True),
    ("Frozen berries", "fruit", 1, 12, 0.5, 5, 57, "g", 180, True),
    ("Kiwi", "fruit", 1.1, 15, 0.5, 3, 61, "item", 14, False),
    ("Apple", "fruit", 0.3, 14, 0.2, 2.4, 52, "item", 21, False),
    ("Banana", "fruit", 1.1, 23, 0.3, 2.6, 89, "item", 7, False),
    ("Orange / clementine", "fruit", 0.9, 12, 0.1, 2.4, 47, "item", 14, False),
    ("Walnuts / mixed nuts", "fat", 15, 14, 65, 7, 654, "g", 180, False),
    ("Flax / chia", "fat", 18, 29, 42, 27, 534, "g", 365, False),
]


def ingredient(name: str, quantity: str) -> dict[str, str]:
    return {"name": name, "quantity": quantity}


MEALS: list[dict[str, Any]] = [
    {
        "name": "Berry protein smoothie",
        "description": "Skyr, berries, oats and seeds blended smooth",
        "ingredients": [
            ingredient("Skyr / quark", "300 g"),
            ingredient("Frozen berries", "150 g"),
            ingredient("Oats", "40 g"),
            ingredient("Flax / chia", "15 g"),
        ],
        "hands": 3,
        "total": 3,
        "batch": 1,
        "fridge": 1,
        "freeze": False,
        "reheat": None,
        "protein": 42,
        "fiber": 12,
        "produce": 1.5,
        "effort": 1,
        "tags": ["snack", "fast"],
    },
    {
        "name": "Skyr fruit bowl",
        "description": "Skyr with fruit, oats and walnuts",
        "ingredients": [
            ingredient("Skyr / quark", "400 g"),
            ingredient("Kiwi", "2"),
            ingredient("Oats", "40 g"),
            ingredient("Walnuts / mixed nuts", "20 g"),
        ],
        "hands": 3,
        "total": 3,
        "batch": 1,
        "fridge": 1,
        "freeze": False,
        "reheat": None,
        "protein": 52,
        "fiber": 9,
        "produce": 2,
        "effort": 1,
        "tags": ["no-cook", "fast"],
    },
    {
        "name": "Chicken power bowl",
        "description": "Chicken, brown rice, broccoli and peppers with yogurt sauce",
        "ingredients": [
            ingredient("Chicken breast", "250 g"),
            ingredient("Brown rice", "200 g cooked"),
            ingredient("Broccoli", "200 g"),
            ingredient("Peppers", "100 g"),
        ],
        "hands": 18,
        "total": 35,
        "batch": 4,
        "fridge": 3,
        "freeze": True,
        "reheat": "Microwave 3-4 minutes",
        "protein": 70,
        "fiber": 11,
        "produce": 3,
        "effort": 3,
        "tags": ["batch", "freezer"],
    },
    {
        "name": "Salmon potato plate",
        "description": "Salmon, potatoes, broccoli and tomato",
        "ingredients": [
            ingredient("Salmon", "220 g"),
            ingredient("Potatoes", "350 g"),
            ingredient("Broccoli", "200 g"),
            ingredient("Tomatoes", "150 g"),
        ],
        "hands": 10,
        "total": 30,
        "batch": 2,
        "fridge": 2,
        "freeze": False,
        "reheat": "Oven or microwave",
        "protein": 55,
        "fiber": 12,
        "produce": 3,
        "effort": 2,
        "tags": ["fish", "sheet-pan"],
    },
    {
        "name": "Egg and cottage cheese plate",
        "description": "Eggs, cottage cheese, wholegrain bread, tomatoes and spinach",
        "ingredients": [
            ingredient("Eggs", "4"),
            ingredient("Cottage cheese", "250 g"),
            ingredient("Wholegrain bread", "120 g"),
            ingredient("Tomatoes", "150 g"),
            ingredient("Spinach", "80 g"),
        ],
        "hands": 8,
        "total": 10,
        "batch": 1,
        "fridge": 1,
        "freeze": False,
        "reheat": None,
        "protein": 62,
        "fiber": 10,
        "produce": 2,
        "effort": 2,
        "tags": ["fast"],
    },
    {
        "name": "Lentil quinoa bowl",
        "description": "Lentils, quinoa, vegetables and yogurt-lemon sauce",
        "ingredients": [
            ingredient("Lentils", "250 g cooked"),
            ingredient("Quinoa", "180 g cooked"),
            ingredient("Frozen mixed vegetables", "250 g"),
        ],
        "hands": 12,
        "total": 25,
        "batch": 4,
        "fridge": 4,
        "freeze": True,
        "reheat": "Microwave 3 minutes",
        "protein": 38,
        "fiber": 24,
        "produce": 3,
        "effort": 2,
        "tags": ["plant", "batch"],
    },
    {
        "name": "Chickpea chicken bowl",
        "description": "Chicken, chickpeas, spinach and tomato",
        "ingredients": [
            ingredient("Chicken breast", "200 g"),
            ingredient("Chickpeas", "180 g cooked"),
            ingredient("Spinach", "100 g"),
            ingredient("Tomatoes", "150 g"),
        ],
        "hands": 12,
        "total": 22,
        "batch": 3,
        "fridge": 3,
        "freeze": True,
        "reheat": "Microwave 3 minutes",
        "protein": 67,
        "fiber": 16,
        "produce": 2,
        "effort": 2,
        "tags": ["batch"],
    },
    {
        "name": "Sardine tomato toast",
        "description": "Sardines and tomato on wholegrain toast with lemon",
        "ingredients": [
            ingredient("Sardines", "160 g"),
            ingredient("Wholegrain bread", "150 g"),
            ingredient("Tomatoes", "200 g"),
        ],
        "hands": 5,
        "total": 5,
        "batch": 1,
        "fridge": 1,
        "freeze": False,
        "reheat": None,
        "protein": 52,
        "fiber": 11,
        "produce": 2,
        "effort": 1,
        "tags": ["pantry", "fast"],
    },
    {
        "name": "Emergency protein plate",
        "description": "Skyr, fruit, nuts and wholegrain bread",
        "ingredients": [
            ingredient("Skyr / quark", "500 g"),
            ingredient("Banana", "1"),
            ingredient("Walnuts / mixed nuts", "30 g"),
            ingredient("Wholegrain bread", "120 g"),
        ],
        "hands": 3,
        "total": 3,
        "batch": 1,
        "fridge": 1,
        "freeze": False,
        "reheat": None,
        "protein": 65,
        "fiber": 12,
        "produce": 1,
        "effort": 1,
        "tags": ["emergency", "no-cook"],
    },
    {
        "name": "Chicken potato tray",
        "description": "Sheet-pan chicken, potatoes, peppers and broccoli",
        "ingredients": [
            ingredient("Chicken breast", "250 g"),
            ingredient("Potatoes", "350 g"),
            ingredient("Peppers", "120 g"),
            ingredient("Broccoli", "180 g"),
        ],
        "hands": 12,
        "total": 35,
        "batch": 4,
        "fridge": 3,
        "freeze": True,
        "reheat": "Oven or microwave",
        "protein": 70,
        "fiber": 13,
        "produce": 3,
        "effort": 2,
        "tags": ["batch", "sheet-pan"],
    },
    {
        "name": "Salmon quinoa bowl",
        "description": "Salmon, quinoa, spinach and peppers",
        "ingredients": [
            ingredient("Salmon", "220 g"),
            ingredient("Quinoa", "200 g cooked"),
            ingredient("Spinach", "100 g"),
            ingredient("Peppers", "120 g"),
        ],
        "hands": 10,
        "total": 25,
        "batch": 2,
        "fridge": 2,
        "freeze": False,
        "reheat": "Microwave gently",
        "protein": 53,
        "fiber": 10,
        "produce": 2,
        "effort": 2,
        "tags": ["fish"],
    },
    {
        "name": "Egg chickpea bowl",
        "description": "Eggs, chickpeas, spinach and tomatoes",
        "ingredients": [
            ingredient("Eggs", "4"),
            ingredient("Chickpeas", "200 g cooked"),
            ingredient("Spinach", "100 g"),
            ingredient("Tomatoes", "180 g"),
        ],
        "hands": 10,
        "total": 12,
        "batch": 1,
        "fridge": 1,
        "freeze": False,
        "reheat": None,
        "protein": 45,
        "fiber": 16,
        "produce": 2,
        "effort": 2,
        "tags": ["fast"],
    },
    {
        "name": "Cottage cheese power toast",
        "description": "Cottage cheese, eggs, tomatoes and wholegrain bread",
        "ingredients": [
            ingredient("Cottage cheese", "300 g"),
            ingredient("Eggs", "3"),
            ingredient("Tomatoes", "180 g"),
            ingredient("Wholegrain bread", "150 g"),
        ],
        "hands": 8,
        "total": 10,
        "batch": 1,
        "fridge": 1,
        "freeze": False,
        "reheat": None,
        "protein": 65,
        "fiber": 11,
        "produce": 2,
        "effort": 2,
        "tags": ["fast"],
    },
    {
        "name": "Chicken quinoa greens",
        "description": "Chicken, quinoa and mixed green vegetables",
        "ingredients": [
            ingredient("Chicken breast", "250 g"),
            ingredient("Quinoa", "200 g cooked"),
            ingredient("Frozen mixed vegetables", "280 g"),
        ],
        "hands": 12,
        "total": 28,
        "batch": 4,
        "fridge": 3,
        "freeze": True,
        "reheat": "Microwave 3 minutes",
        "protein": 70,
        "fiber": 12,
        "produce": 3,
        "effort": 2,
        "tags": ["batch", "freezer"],
    },
    {
        "name": "Lentil egg plate",
        "description": "Warm lentils with eggs, spinach and tomatoes",
        "ingredients": [
            ingredient("Lentils", "300 g cooked"),
            ingredient("Eggs", "4"),
            ingredient("Spinach", "100 g"),
            ingredient("Tomatoes", "180 g"),
        ],
        "hands": 10,
        "total": 15,
        "batch": 2,
        "fridge": 2,
        "freeze": False,
        "reheat": "Microwave lentils separately",
        "protein": 48,
        "fiber": 26,
        "produce": 2,
        "effort": 2,
        "tags": ["high-fiber"],
    },
    {
        "name": "Sardine potato salad",
        "description": "Sardines, potatoes, spinach and tomatoes",
        "ingredients": [
            ingredient("Sardines", "160 g"),
            ingredient("Potatoes", "350 g"),
            ingredient("Spinach", "100 g"),
            ingredient("Tomatoes", "180 g"),
        ],
        "hands": 10,
        "total": 25,
        "batch": 2,
        "fridge": 2,
        "freeze": False,
        "reheat": None,
        "protein": 48,
        "fiber": 11,
        "produce": 2,
        "effort": 2,
        "tags": ["fish"],
    },
    {
        "name": "Thursday flexible colleague meal",
        "description": "Choose a clear protein source, vegetables or salad, and carbohydrates according to hunger",
        "ingredients": [],
        "hands": 0,
        "total": 0,
        "batch": 1,
        "fridge": None,
        "freeze": False,
        "reheat": None,
        "protein": 40,
        "fiber": 8,
        "produce": 2,
        "effort": 1,
        "tags": ["office", "flexible"],
    },
]


def seed_all(db: Session, settings: Settings) -> UserProfile:
    account = db.scalar(select(UserAccount).where(UserAccount.email == settings.bootstrap_email))
    if account is None:
        account = UserAccount(
            email=settings.bootstrap_email,
            password_hash=hash_password(settings.bootstrap_password.get_secret_value()),
        )
        db.add(account)
        db.flush()

    profile = db.scalar(select(UserProfile).where(UserProfile.account_id == account.id))
    if profile is None:
        profile = UserProfile(
            account_id=account.id,
            timezone="Europe/Zurich",
            location="Zurich, Switzerland",
            weight_kg=90,
            height_cm=180,
            primary_training_goal=PRIMARY_GOAL,
            max_main_meals_per_day=2,
            preferred_main_meals_per_day=2,
            max_exercises_per_day=3,
            gym_days=["Saturday", "Sunday"],
            office_days=["Thursday"],
            excluded_exercises=["squat", "back squat", "front squat"],
            nutrition_preferences={
                "protein_range_g": [145, 170],
                "max_prep_sessions_per_day": 1,
                "prefer_batch_freezing": True,
                "thursday_commute_minutes": 180,
            },
            allergies=[],
            medical_constraints=[
                "Avoid squat-based programming due to waist/lower-back discomfort",
                "Do not progress movements associated with pain",
            ],
            strength_capacity_json={
                "bench_press": {"load_kg": 100, "reps_range": [5, 8], "confidence": "recorded"},
                "strict_pull_up": {"reps": ">10", "confidence": "recorded"},
            },
            endurance_capacity_json={
                "running": {"status": "unknown", "goal_distance_km": [8, 12], "confidence": "goal"},
                "cycling_ftp_watts": None,
            },
            kitchen_equipment_json=[
                {"name": "High-quality blender", "owned": True},
                {"name": "Multicooker or rice cooker", "owned": None},
                {"name": "Air fryer or convection oven", "owned": None},
                {"name": "Digital kitchen scale", "owned": None},
                {"name": "Instant-read meat thermometer", "owned": None},
                {"name": "10 freezer-safe meal containers", "owned": None},
                {"name": "Large sheet pan", "owned": None},
                {"name": "Chef's knife", "owned": None},
            ],
        )
        db.add(profile)

    for name, category, details in EQUIPMENT:
        if db.scalar(select(Equipment).where(Equipment.name == name)) is None:
            db.add(Equipment(name=name, category=category, details_json=details))

    for name, category, required, gym_only, compound, measurement in EXERCISES:
        if db.scalar(select(Exercise).where(Exercise.name == name)) is None:
            db.add(
                Exercise(
                    name=name,
                    category=category,
                    equipment_required=required,
                    gym_only=gym_only,
                    compound=compound,
                    measurement_type=measurement,
                    pain_exclusion_tags=["lower_back"]
                    if name in {"Deadlift", "Romanian deadlift"}
                    else [],
                )
            )

    for values in FOODS:
        if db.scalar(select(FoodItem).where(FoodItem.name == values[0])) is None:
            db.add(
                FoodItem(
                    name=values[0],
                    category=values[1],
                    protein_g_per_100=values[2],
                    carbs_g_per_100=values[3],
                    fat_g_per_100=values[4],
                    fiber_g_per_100=values[5],
                    calories_per_100=values[6],
                    typical_unit=values[7],
                    shelf_life_days=values[8],
                    freezer_friendly=values[9],
                )
            )

    for meal in MEALS:
        if db.scalar(select(MealTemplate).where(MealTemplate.name == meal["name"])) is None:
            db.add(
                MealTemplate(
                    name=meal["name"],
                    description=meal["description"],
                    ingredients_json=meal["ingredients"],
                    servings=1,
                    hands_on_minutes=meal["hands"],
                    total_minutes=meal["total"],
                    batch_size=meal["batch"],
                    fridge_life_days=meal["fridge"],
                    freezer_friendly=meal["freeze"],
                    reheat_method=meal["reheat"],
                    estimated_protein_g=meal["protein"],
                    estimated_fiber_g=meal["fiber"],
                    produce_portions=meal["produce"],
                    effort_score=meal["effort"],
                    tags=meal["tags"],
                )
            )

    if settings.extension_api_token:
        raw_token = settings.extension_api_token.get_secret_value()
        digest = token_digest(raw_token, settings)
        if db.scalar(select(ApiToken).where(ApiToken.token_hash == digest)) is None:
            db.add(ApiToken(account_id=account.id, name="Environment bootstrap", token_hash=digest))

    db.commit()
    db.refresh(profile)
    return profile
