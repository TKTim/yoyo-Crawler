"""
Unified AI API — tries Gemini first, falls back to OpenRouter on failure.
Callers import from here instead of individual providers.
"""
import logging

from . import gemini_api
from . import openrouter_api

logger = logging.getLogger(__name__)


def estimate_nutrition(food_name, description=''):
    result = gemini_api.estimate_nutrition(food_name, description)
    if result['calories'] is not None:
        return result
    logger.info("Gemini failed for estimate_nutrition, falling back to OpenRouter")
    return openrouter_api.estimate_nutrition(food_name, description)


def estimate_nutrition_from_image(image_bytes, mime_type):
    result = gemini_api.estimate_nutrition_from_image(image_bytes, mime_type)
    if result['food_name'] is not None:
        return result
    logger.info("Gemini failed for estimate_nutrition_from_image, falling back to OpenRouter")
    return openrouter_api.estimate_nutrition_from_image(image_bytes, mime_type)


def parse_and_estimate_foods(text):
    result = gemini_api.parse_and_estimate_foods(text)
    if result is not None:
        return result
    logger.info("Gemini failed for parse_and_estimate_foods, falling back to OpenRouter")
    return openrouter_api.parse_and_estimate_foods(text)


def modify_food_estimation(original_food, modification):
    result = gemini_api.modify_food_estimation(original_food, modification)
    if result is not None:
        return result
    logger.info("Gemini failed for modify_food_estimation, falling back to OpenRouter")
    return openrouter_api.modify_food_estimation(original_food, modification)


def generate_diet_advice(foods, tdee=None, user_prompt=''):
    result = gemini_api.generate_diet_advice(foods, tdee, user_prompt)
    if result is not None:
        return result
    logger.info("Gemini failed for generate_diet_advice, falling back to OpenRouter")
    return openrouter_api.generate_diet_advice(foods, tdee, user_prompt)
