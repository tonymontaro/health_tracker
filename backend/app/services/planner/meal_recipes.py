from app.db.models import MealTemplate

RECIPE_STEPS: dict[str, tuple[str, ...]] = {
    "Berry protein smoothie": (
        "Put the skyr, frozen berries, oats, and seeds in a blender.",
        "Blend until smooth, adding a small splash of water only if needed, then serve.",
    ),
    "Skyr fruit bowl": (
        "Spoon the skyr into a bowl and stir in the oats.",
        "Peel and slice the kiwi, then add it with the walnuts and serve.",
    ),
    "Chicken power bowl": (
        "Season the chicken and cook it in a covered nonstick pan over medium heat for 12-15 minutes, turning once, until cooked through.",
        "Steam the broccoli and peppers for 6-8 minutes and warm the cooked brown rice.",
        "Slice the chicken, arrange everything in a bowl, and season to taste.",
    ),
    "Salmon potato plate": (
        "Cut the potatoes into small pieces and roast them at 200 C for about 25 minutes.",
        "Add the salmon and broccoli to the tray for the final 12-15 minutes, until the salmon flakes easily and the vegetables are tender.",
        "Serve with the chopped tomatoes.",
    ),
    "Egg and cottage cheese plate": (
        "Scramble or boil the eggs until cooked to your liking and toast the bread.",
        "Wilt the spinach briefly in the warm pan, then plate it with the eggs, cottage cheese, toast, and sliced tomatoes.",
    ),
    "Lentil quinoa bowl": (
        "Warm the cooked lentils, cooked quinoa, and mixed vegetables together in a covered pan for 8-10 minutes.",
        "Stir until hot throughout, season to taste, and divide into bowls.",
    ),
    "Chickpea chicken bowl": (
        "Cut up the chicken and cook it in a covered nonstick pan over medium heat for 8-10 minutes, until cooked through.",
        "Add the chickpeas, spinach, and chopped tomatoes and cook for another 4-5 minutes.",
        "Season to taste and serve warm.",
    ),
    "Sardine tomato toast": (
        "Toast the wholegrain bread and slice the tomatoes.",
        "Top the toast with the tomatoes and drained sardines, season to taste, and serve.",
    ),
    "Emergency protein plate": (
        "Put the skyr in a bowl and add the sliced banana and nuts.",
        "Serve with the wholegrain bread; no cooking is needed.",
    ),
    "Chicken potato tray": (
        "Heat the oven to 200 C, cut the potatoes and vegetables into bite-size pieces, and spread them on a tray.",
        "Add the chicken, season everything, and roast for 25-30 minutes, turning the vegetables once, until the chicken is cooked through.",
    ),
    "Salmon quinoa bowl": (
        "Bake or pan-cook the salmon for 10-14 minutes, until it flakes easily.",
        "Warm the cooked quinoa with the spinach and sliced peppers for 5-7 minutes.",
        "Flake the salmon over the quinoa and vegetables, then serve.",
    ),
    "Egg chickpea bowl": (
        "Warm the chickpeas, spinach, and chopped tomatoes in a covered pan for 5-6 minutes.",
        "Scramble the eggs into the same pan until set, season to taste, and serve in a bowl.",
    ),
    "Cottage cheese power toast": (
        "Toast the bread and scramble or boil the eggs until set.",
        "Spread the cottage cheese over the toast and top or serve it with the eggs and sliced tomatoes.",
    ),
    "Chicken quinoa greens": (
        "Cut up the chicken and cook it in a covered nonstick pan over medium heat for 8-10 minutes, until cooked through.",
        "Add the mixed vegetables and cook for 5-6 minutes, then stir in the cooked quinoa until hot.",
        "Season to taste and serve.",
    ),
    "Lentil egg plate": (
        "Warm the cooked lentils, spinach, and chopped tomatoes in a covered pan for 5-7 minutes.",
        "Cook the eggs separately by boiling, frying, or scrambling them, then serve them over the warm lentil mixture.",
    ),
    "Sardine potato salad": (
        "Cut the potatoes into small pieces and boil them for 12-15 minutes, until tender, then drain and cool slightly.",
        "Toss the potatoes with the spinach, chopped tomatoes, and drained sardines, then season to taste.",
    ),
    "Thursday flexible colleague meal": (
        "Choose one clear protein, one serving of vegetables or salad, and a carbohydrate according to hunger.",
        "Ask for sauces or dressings on the side, assemble a balanced plate, and eat until comfortably satisfied.",
    ),
}


def simple_meal_recipe(template: MealTemplate) -> str:
    steps = list(RECIPE_STEPS.get(template.name, ()))
    if not steps:
        ingredient_names = (
            ", ".join(str(item.get("name", "ingredient")) for item in template.ingredients_json)
            or "the listed ingredients"
        )
        steps = [
            f"Prepare any raw items among {ingredient_names} until safely cooked.",
            "Warm or chop the remaining ingredients as appropriate, combine them, and serve.",
        ]
    if template.batch_size > 1:
        steps.insert(
            0,
            f"For {template.batch_size} servings, multiply each listed quantity by {template.batch_size}.",
        )
        steps[-1] += f" Divide the finished meal into {template.batch_size} portions."
    return " ".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
