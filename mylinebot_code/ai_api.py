"""
Unified AI API — tries the primary provider first, falls back to the other on failure.
Callers import from here instead of individual providers.

Set AI_PRIMARY_PROVIDER env var to 'gemini' (default) or 'openrouter'.
"""
import logging
import os

from . import gemini_api
from . import openrouter_api

logger = logging.getLogger(__name__)

_PRIMARY = os.environ.get('AI_PRIMARY_PROVIDER', 'gemini').lower()

if _PRIMARY == 'openrouter':
    _primary = openrouter_api
    _fallback = gemini_api
else:
    _primary = gemini_api
    _fallback = openrouter_api

logger.info(f"AI primary provider: {_PRIMARY}")


def estimate_nutrition(food_name, description=''):
    result = _primary.estimate_nutrition(food_name, description)
    if result['calories'] is not None:
        return result
    logger.info("Primary failed for estimate_nutrition, falling back")
    return _fallback.estimate_nutrition(food_name, description)


def estimate_nutrition_from_image(image_bytes, mime_type):
    result = _primary.estimate_nutrition_from_image(image_bytes, mime_type)
    if result['food_name'] is not None:
        return result
    logger.info("Primary failed for estimate_nutrition_from_image, falling back")
    return _fallback.estimate_nutrition_from_image(image_bytes, mime_type)


def parse_and_estimate_foods(text):
    result = _primary.parse_and_estimate_foods(text)
    if result is not None:
        return result
    logger.info("Primary failed for parse_and_estimate_foods, falling back")
    return _fallback.parse_and_estimate_foods(text)


def modify_food_estimation(original_food, modification):
    result = _primary.modify_food_estimation(original_food, modification)
    if result is not None:
        return result
    logger.info("Primary failed for modify_food_estimation, falling back")
    return _fallback.modify_food_estimation(original_food, modification)


def generate_diet_advice(foods, tdee=None, user_prompt=''):
    result = _primary.generate_diet_advice(foods, tdee, user_prompt)
    if result is not None:
        return result
    logger.info("Primary failed for generate_diet_advice, falling back")
    return _fallback.generate_diet_advice(foods, tdee, user_prompt)
