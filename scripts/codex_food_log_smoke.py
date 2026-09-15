"""Run a privacy-safe food extraction smoke test with fictitious data."""

from app.core.config import get_settings
from app.services.food_log import FoodLogExtractor

SYNTHETIC_RECOMMENDATIONS = [
    {
        "recommendation_id": "synthetic-lentil-bowl",
        "meal_slot": "meal_1",
        "name": "Lentil soup and wholegrain bread",
        "description": "A bowl of lentil soup served with wholegrain bread.",
        "quantity": {"estimated_protein_g": 28},
    },
    {
        "recommendation_id": "synthetic-kiwi",
        "meal_slot": "fruit",
        "name": "Kiwi",
        "description": "Two kiwis.",
        "quantity": {"quantity": "2 items"},
    },
]

SYNTHETIC_CATALOG = [
    {
        "name": "Lentils",
        "category": "legume",
        "typical_unit": "g cooked",
        "protein_g_per_100": 9,
        "carbs_g_per_100": 20,
        "fat_g_per_100": 0.4,
        "fiber_g_per_100": 8,
        "calories_per_100": 116,
    },
    {
        "name": "Wholegrain bread",
        "category": "carbohydrate",
        "typical_unit": "g",
        "protein_g_per_100": 13,
        "carbs_g_per_100": 41,
        "fat_g_per_100": 4.2,
        "fiber_g_per_100": 7,
        "calories_per_100": 247,
    },
    {
        "name": "Apple",
        "category": "fruit",
        "typical_unit": "item",
        "protein_g_per_100": 0.3,
        "carbs_g_per_100": 14,
        "fat_g_per_100": 0.2,
        "fiber_g_per_100": 2.4,
        "calories_per_100": 52,
    },
]


def main() -> None:
    settings = get_settings()
    extractor = FoodLogExtractor(settings)
    result = extractor.extract(
        "I ate a bowl of lentil soup with a slice of wholegrain bread, then an apple.",
        SYNTHETIC_RECOMMENDATIONS,
        SYNTHETIC_CATALOG,
    )
    print(
        {
            "synthetic_test_data": True,
            "model": extractor.model,
            "parsed": True,
            "meal_count": len(result.meals),
            "meal_names": [meal.meal_name for meal in result.meals],
            "component_count": sum(len(meal.components) for meal in result.meals),
            "matched_recommendation_ids": [
                meal.matched_recommendation_id
                for meal in result.meals
                if meal.matched_recommendation_id
            ],
            "assumed_component_count": sum(
                component.quantity_is_assumed
                for meal in result.meals
                for component in meal.components
            ),
        }
    )


if __name__ == "__main__":
    main()
