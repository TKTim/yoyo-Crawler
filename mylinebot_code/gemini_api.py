"""
Google Gemini API client for nutrition estimation.
Uses gemini-2.5-flash-lite-preview-06-17 (free tier).
"""
import base64
import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = 'gemini-2.5-flash-lite'
GEMINI_URL = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'


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
        response = requests.post(
            GEMINI_URL,
            params={'key': GEMINI_API_KEY},
            json={
                'contents': [{'parts': [{'text': prompt}]}]
            },
            timeout=15
        )
        response.raise_for_status()

        data = response.json()
        text = data['candidates'][0]['content']['parts'][0]['text']

        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()
        if text.startswith('json'):
            text = text[4:].strip()

        result = json.loads(text)
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
        response = requests.post(
            GEMINI_URL,
            params={'key': GEMINI_API_KEY},
            json={
                'contents': [{
                    'parts': [
                        {'inline_data': {'mime_type': mime_type, 'data': image_b64}},
                        {'text': prompt},
                    ]
                }]
            },
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        text = data['candidates'][0]['content']['parts'][0]['text']

        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()
        if text.startswith('json'):
            text = text[4:].strip()

        result = json.loads(text)
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
        response = requests.post(
            GEMINI_URL,
            params={'key': GEMINI_API_KEY},
            json={
                'contents': [{'parts': [{'text': prompt}]}]
            },
            timeout=15
        )
        response.raise_for_status()

        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        logger.error(f"Gemini diet advice error: {e}")
        return None
