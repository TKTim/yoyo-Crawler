"""
Centralized AI prompt templates for nutrition estimation.
All prompt strings live here so providers (Gemini, OpenRouter) share identical prompts.
"""


def nutrition_prompt(food_desc):
    """Prompt for estimating nutrition of a described food item."""
    return (
        f"Estimate the nutritional content of this food: \"{food_desc}\".\n"
        "Return ONLY a JSON object with these fields (no markdown, no extra text):\n"
        '{"calories": <number>, "protein": <number>, "carbs": <number>, "fat": <number>, "basis": "<brief explanation>"}\n'
        "Values should be in kcal for calories and grams for protein/carbs/fat.\n"
        '"basis" should be a short explanation (under 80 chars) of what you assumed (e.g. "1 medium apple ~182g").\n'
        "If you cannot estimate, use 0 for all values."
    )


def image_nutrition_prompt():
    """Prompt for estimating nutrition from a food photo."""
    return (
        "Look at this food photo and estimate its nutritional content.\n"
        "Return ONLY a JSON object with these fields (no markdown, no extra text):\n"
        '{"food_name": "<name of the food>", "calories": <number>, "protein": <number>, "carbs": <number>, "fat": <number>, "basis": "<brief explanation>"}\n'
        "Values should be in kcal for calories and grams for protein/carbs/fat.\n"
        '"food_name" should be a concise name for the food (e.g. "Chicken rice", "Caesar salad").\n'
        '"basis" should be a short explanation (under 80 chars) of what you assumed (e.g. "1 bowl of chicken rice ~400g").\n'
        "If you cannot identify the food, use null for food_name and 0 for all values."
    )


def parse_foods_prompt(text):
    """Prompt for parsing free-form text into food items with nutrition."""
    return (
        f"The user described what they ate: \"{text}\".\n"
        "Identify the food items and estimate nutritional content for each.\n"
        "IMPORTANT splitting rules:\n"
        "- If the user describes ONE composite dish (e.g. \u4fbf\u7576, \u5957\u9910, a sandwich with toppings), "
        "keep it as ONE item. Use the dish name as \"name\" and put ingredients/details in \"description\".\n"
        "  Example: \"\u9b6a\u9b5a\u852c\u83dc\u4fbf\u7576\" \u2192 name: \"\u4fbf\u7576\", description: \"\u9b6a\u9b5a\u3001\u852c\u83dc\"\n"
        "- Only split into multiple items when the user clearly lists SEPARATE dishes/foods "
        "(e.g. \"\u4e00\u500b\u86cb\u548c\u4e00\u676f\u8c46\u6f3f\" \u2192 2 items).\n"
        "Return ONLY a JSON array (even for a single item) with objects containing these fields:\n"
        '[{"name": "<main food name>", "description": "<ingredients or details, or empty string>", '
        '"calories": <number>, "protein": <number>, "carbs": <number>, "fat": <number>, "basis": "<brief explanation>"}]\n'
        "Values should be in kcal for calories and grams for protein/carbs/fat.\n"
        '"name" should be concise (the primary dish/food name).\n'
        '"description" should contain composition details if relevant, or empty string if not needed.\n'
        '"basis" should be a short explanation (under 80 chars) of what you assumed (e.g. "1\u986f\u714e\u86cb~46g").\n'
        "If a quantity is mentioned, use it. Otherwise assume a typical single serving.\n"
        "If you cannot estimate, use 0 for all values."
    )


def modify_food_prompt(original_desc, original_nutrition, basis, modification):
    """Prompt for re-estimating a food entry after user modification."""
    return (
        f"Original food entry: \"{original_desc}\"\n"
        f"Original nutrition: {original_nutrition}\n"
        f"Original basis: \"{basis}\"\n\n"
        f"User wants to modify: \"{modification}\"\n\n"
        "Based on the modification, re-estimate the food entry.\n"
        "The modification may change the food name, portion size, ingredients, or other details.\n"
        "Return ONLY a JSON object with these fields (no markdown, no extra text):\n"
        '{"name": "<updated food name>", "description": "<updated details>", '
        '"calories": <number>, "protein": <number>, "carbs": <number>, "fat": <number>, '
        '"basis": "<brief explanation of what changed>"}\n'
        "Values should be in kcal for calories and grams for protein/carbs/fat.\n"
        '"basis" should explain what was adjusted (under 80 chars).\n'
    )


def diet_advice_prompt(food_list, total_cal, tdee_info, question):
    """Prompt for generating dietary advice based on today's food log."""
    return (
        f"Today's food log:\n{food_list}\n"
        f"Total so far: {total_cal:.0f} kcal{tdee_info}\n\n"
        f"User's question: {question}\n"
        "Answer in the same language as the user's question. Be concise and practical."
    )
