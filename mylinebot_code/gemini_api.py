"""
Google Gemini API client for nutrition estimation.
Uses gemini-2.0-flash (free tier: 15 RPM, 1M tokens/day).
"""
import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = 'gemini-2.0-flash'
GEMINI_URL = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'


def estimate_nutrition(food_name, description=''):
    """
    Call Gemini API to estimate nutrition for a food item.
    Returns dict with keys: calories, protein, carbs, fat.
    Values are floats or None if estimation fails.
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set, cannot estimate nutrition")
        return {'calories': None, 'protein': None, 'carbs': None, 'fat': None}

    food_desc = food_name
    if description:
        food_desc = f"{food_name}, {description}"

    prompt = (
        f"Estimate the nutritional content of this food: \"{food_desc}\".\n"
        "Return ONLY a JSON object with these numeric fields (no markdown, no explanation):\n"
        '{"calories": <number>, "protein": <number>, "carbs": <number>, "fat": <number>}\n'
        "Values should be in kcal for calories and grams for protein/carbs/fat.\n"
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
        }
    except Exception as e:
        logger.error(f"Gemini API error for '{food_desc}': {e}")
        return {'calories': None, 'protein': None, 'carbs': None, 'fat': None}
