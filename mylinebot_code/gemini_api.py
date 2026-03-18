"""
Google Gemini API client for nutrition estimation.
Tries multiple models with automatic fallback on rate limit / quota errors.
"""
import base64
import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/models'

# Models to try in order — falls back to next on rate limit / quota / server errors
GEMINI_MODELS = [
    'gemini-2.5-flash-lite',
    'gemini-2.5-flash',
    'gemini-2.0-flash-lite',
]

# HTTP status codes that trigger fallback to next model
_RETRYABLE_STATUS_CODES = {429, 500, 503, 403}


def _gemini_request(payload, timeout=15):
    """
    Send a request to Gemini API, trying each model in GEMINI_MODELS until one succeeds.
    Returns the parsed JSON response data, or raises the last exception on total failure.
    """
    last_error = None
    for model in GEMINI_MODELS:
        url = f'{GEMINI_BASE_URL}/{model}:generateContent'
        try:
            response = requests.post(
                url,
                params={'key': GEMINI_API_KEY},
                json=payload,
                timeout=timeout,
            )
            if response.status_code in _RETRYABLE_STATUS_CODES:
                logger.warning(f"Gemini model {model} returned {response.status_code}, trying next model")
                last_error = requests.exceptions.HTTPError(
                    f"{response.status_code} for model {model}", response=response
                )
                continue
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            logger.warning(f"Gemini model {model} timed out, trying next model")
            last_error = e
            continue
        except requests.exceptions.HTTPError:
            raise
        except Exception as e:
            logger.warning(f"Gemini model {model} failed: {e}, trying next model")
            last_error = e
            continue
    raise last_error


def _parse_gemini_json(data):
    """Extract and parse JSON from Gemini response text."""
    text = data['candidates'][0]['content']['parts'][0]['text']
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()
    if text.startswith('json'):
        text = text[4:].strip()
    return json.loads(text)


def estimate_nutrition(food_name, description=''):
    """
    Call Gemini API to estimate nutrition for a food item.
    Returns dict with keys: calories, protein, carbs, fat.
    Values are floats or None if estimation fails.
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set, cannot estimate nutrition")
        return {'calories': None, 'protein': None, 'carbs': None, 'fat': None, 'basis': ''}

    food_desc = food_name
    if description:
        food_desc = f"{food_name}, {description}"

    prompt = (
        f"Estimate the nutritional content of this food: \"{food_desc}\".\n"
        "Return ONLY a JSON object with these fields (no markdown, no extra text):\n"
        '{"calories": <number>, "protein": <number>, "carbs": <number>, "fat": <number>, "basis": "<brief explanation>"}\n'
        "Values should be in kcal for calories and grams for protein/carbs/fat.\n"
        '"basis" should be a short explanation (under 80 chars) of what you assumed (e.g. "1 medium apple ~182g").\n'
        "If you cannot estimate, use 0 for all values."
    )

    try:
        data = _gemini_request({'contents': [{'parts': [{'text': prompt}]}]}, timeout=15)
        result = _parse_gemini_json(data)
        return {
            'calories': float(result.get('calories', 0)),
            'protein': float(result.get('protein', 0)),
            'carbs': float(result.get('carbs', 0)),
            'fat': float(result.get('fat', 0)),
            'basis': result.get('basis', ''),
        }
    except Exception as e:
        logger.error(f"Gemini API error for '{food_desc}': {e}")
        return {'calories': None, 'protein': None, 'carbs': None, 'fat': None, 'basis': ''}


def estimate_nutrition_from_image(image_bytes, mime_type):
    """
    Call Gemini API to estimate nutrition from a food photo.
    Returns dict with keys: food_name, calories, protein, carbs, fat, basis.
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set, cannot estimate nutrition from image")
        return {'food_name': None, 'calories': None, 'protein': None, 'carbs': None, 'fat': None, 'basis': ''}

    image_b64 = base64.b64encode(image_bytes).decode('utf-8')

    prompt = (
        "Look at this food photo and estimate its nutritional content.\n"
        "Return ONLY a JSON object with these fields (no markdown, no extra text):\n"
        '{"food_name": "<name of the food>", "calories": <number>, "protein": <number>, "carbs": <number>, "fat": <number>, "basis": "<brief explanation>"}\n'
        "Values should be in kcal for calories and grams for protein/carbs/fat.\n"
        '"food_name" should be a concise name for the food (e.g. "Chicken rice", "Caesar salad").\n'
        '"basis" should be a short explanation (under 80 chars) of what you assumed (e.g. "1 bowl of chicken rice ~400g").\n'
        "If you cannot identify the food, use null for food_name and 0 for all values."
    )

    try:
        payload = {
            'contents': [{
                'parts': [
                    {'inline_data': {'mime_type': mime_type, 'data': image_b64}},
                    {'text': prompt},
                ]
            }]
        }
        data = _gemini_request(payload, timeout=30)
        result = _parse_gemini_json(data)
        return {
            'food_name': result.get('food_name'),
            'calories': float(result.get('calories', 0)),
            'protein': float(result.get('protein', 0)),
            'carbs': float(result.get('carbs', 0)),
            'fat': float(result.get('fat', 0)),
            'basis': result.get('basis', ''),
        }
    except Exception as e:
        logger.error(f"Gemini API image error: {e}")
        return {'food_name': None, 'calories': None, 'protein': None, 'carbs': None, 'fat': None, 'basis': ''}


def parse_and_estimate_foods(text):
    """
    Parse free-form text describing one or more foods and estimate nutrition for each.
    Returns a list of dicts, each with keys: name, calories, protein, carbs, fat, basis.
    Returns None on failure.
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set, cannot parse foods")
        return None

    prompt = (
        f"The user described what they ate: \"{text}\".\n"
        "Identify the food items and estimate nutritional content for each.\n"
        "IMPORTANT splitting rules:\n"
        "- If the user describes ONE composite dish (e.g. 便當, 套餐, a sandwich with toppings), "
        "keep it as ONE item. Use the dish name as \"name\" and put ingredients/details in \"description\".\n"
        "  Example: \"鮪魚蔬菜便當\" → name: \"便當\", description: \"鮪魚、蔬菜\"\n"
        "- Only split into multiple items when the user clearly lists SEPARATE dishes/foods "
        "(e.g. \"一顆蛋和一杯豆漿\" → 2 items).\n"
        "Return ONLY a JSON array (even for a single item) with objects containing these fields:\n"
        '[{"name": "<main food name>", "description": "<ingredients or details, or empty string>", '
        '"calories": <number>, "protein": <number>, "carbs": <number>, "fat": <number>, "basis": "<brief explanation>"}]\n'
        "Values should be in kcal for calories and grams for protein/carbs/fat.\n"
        '"name" should be concise (the primary dish/food name).\n'
        '"description" should contain composition details if relevant, or empty string if not needed.\n'
        '"basis" should be a short explanation (under 80 chars) of what you assumed (e.g. "1顆煎蛋~46g").\n'
        "If a quantity is mentioned, use it. Otherwise assume a typical single serving.\n"
        "If you cannot estimate, use 0 for all values."
    )

    try:
        data = _gemini_request({'contents': [{'parts': [{'text': prompt}]}]}, timeout=15)
        result = _parse_gemini_json(data)
        if isinstance(result, dict):
            result = [result]
        foods = []
        for item in result:
            foods.append({
                'name': item.get('name', ''),
                'description': item.get('description', ''),
                'calories': float(item.get('calories', 0)),
                'protein': float(item.get('protein', 0)),
                'carbs': float(item.get('carbs', 0)),
                'fat': float(item.get('fat', 0)),
                'basis': item.get('basis', ''),
            })
        return foods if foods else None
    except Exception as e:
        logger.error(f"Gemini API error for parse_and_estimate_foods: {e}")
        return None


def generate_diet_advice(foods, tdee=None, user_prompt=''):
    """
    Ask Gemini for dietary advice based on today's food log.
    Returns advice string, or None on failure.
    """
    if not GEMINI_API_KEY:
        return None

    food_summary = []
    total_cal = 0
    for f in foods:
        cal = f.get('calories')
        if cal is not None:
            food_summary.append(f"- {f['name']}: {cal:.0f} kcal, {f.get('protein', 0):.1f}g P, {f.get('carbs', 0):.1f}g C, {f.get('fat', 0):.1f}g F")
            total_cal += cal
        else:
            food_summary.append(f"- {f['name']}: nutrition unknown")

    food_list = "\n".join(food_summary) if food_summary else "No food logged."

    tdee_info = ""
    if tdee:
        remaining = tdee - total_cal
        tdee_info = f"\nUser's TDEE: {tdee} kcal/day. Remaining budget: {remaining:.0f} kcal."

    if user_prompt:
        question = user_prompt
    else:
        question = "Give brief dietary advice based on today's intake. What's missing? What should I eat next? Keep it concise (under 200 characters)."

    prompt = (
        f"Today's food log:\n{food_list}\n"
        f"Total so far: {total_cal:.0f} kcal{tdee_info}\n\n"
        f"User's question: {question}\n"
        "Answer in the same language as the user's question. Be concise and practical."
    )

    try:
        data = _gemini_request({'contents': [{'parts': [{'text': prompt}]}]}, timeout=15)
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        logger.error(f"Gemini diet advice error: {e}")
        return None
