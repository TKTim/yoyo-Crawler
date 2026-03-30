"""
OpenRouter API client for nutrition estimation.
Fallback provider when Gemini is unavailable.
Uses OpenAI-compatible chat completions format with free-tier models.
"""
import base64
import json
import logging
import os

import requests

from .ai_prompts import (
    nutrition_prompt, image_nutrition_prompt, parse_foods_prompt,
    modify_food_prompt, diet_advice_prompt,
)

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get('OPEN_ROUTER_ID', '')
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'

# Vision-capable models first, text-only fallback last
VISION_MODELS = [
    'google/gemma-3-27b-it:free',
    'mistralai/mistral-small-3.1-24b-instruct:free',
]

TEXT_MODELS = VISION_MODELS + [
    'nvidia/nemotron-3-super-120b-a12b:free',
]

_RETRYABLE_STATUS_CODES = {429, 500, 503}


def _openrouter_request(messages, model_list=None, timeout=30):
    """
    Send a chat completion request to OpenRouter, trying each model in order.
    Returns the response text content, or raises the last exception on total failure.
    """
    if model_list is None:
        model_list = TEXT_MODELS

    if not OPENROUTER_API_KEY:
        raise ValueError("OPEN_ROUTER_ID not set")

    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
    }

    last_error = None
    for model in model_list:
        try:
            payload = {
                'model': model,
                'messages': messages,
            }
            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            if response.status_code in _RETRYABLE_STATUS_CODES:
                logger.warning(f"OpenRouter model {model} returned {response.status_code}, trying next model")
                last_error = requests.exceptions.HTTPError(
                    f"{response.status_code} for model {model}", response=response
                )
                continue
            response.raise_for_status()
            data = response.json()
            return data['choices'][0]['message']['content']
        except requests.exceptions.Timeout as e:
            logger.warning(f"OpenRouter model {model} timed out, trying next model")
            last_error = e
            continue
        except requests.exceptions.HTTPError:
            raise
        except Exception as e:
            logger.warning(f"OpenRouter model {model} failed: {e}, trying next model")
            last_error = e
            continue
    raise last_error


def _parse_response_json(text):
    """Extract and parse JSON from response text (handles markdown fences)."""
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
    Call OpenRouter API to estimate nutrition for a food item.
    Returns dict with keys: calories, protein, carbs, fat, basis.
    """
    if not OPENROUTER_API_KEY:
        logger.warning("OPEN_ROUTER_ID not set, cannot estimate nutrition")
        return {'calories': None, 'protein': None, 'carbs': None, 'fat': None, 'basis': ''}

    food_desc = food_name
    if description:
        food_desc = f"{food_name}, {description}"

    prompt = nutrition_prompt(food_desc)

    try:
        messages = [{'role': 'user', 'content': prompt}]
        text = _openrouter_request(messages, TEXT_MODELS)
        result = _parse_response_json(text)
        return {
            'calories': float(result.get('calories', 0)),
            'protein': float(result.get('protein', 0)),
            'carbs': float(result.get('carbs', 0)),
            'fat': float(result.get('fat', 0)),
            'basis': result.get('basis', ''),
        }
    except Exception as e:
        logger.error(f"OpenRouter API error for '{food_desc}': {e}")
        return {'calories': None, 'protein': None, 'carbs': None, 'fat': None, 'basis': ''}


def estimate_nutrition_from_image(image_bytes, mime_type):
    """
    Call OpenRouter API to estimate nutrition from a food photo.
    Returns dict with keys: food_name, calories, protein, carbs, fat, basis.
    """
    if not OPENROUTER_API_KEY:
        logger.warning("OPEN_ROUTER_ID not set, cannot estimate nutrition from image")
        return {'food_name': None, 'calories': None, 'protein': None, 'carbs': None, 'fat': None, 'basis': ''}

    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    prompt = image_nutrition_prompt()

    try:
        messages = [{
            'role': 'user',
            'content': [
                {
                    'type': 'image_url',
                    'image_url': {'url': f'data:{mime_type};base64,{image_b64}'},
                },
                {'type': 'text', 'text': prompt},
            ],
        }]
        text = _openrouter_request(messages, VISION_MODELS, timeout=45)
        result = _parse_response_json(text)
        return {
            'food_name': result.get('food_name'),
            'calories': float(result.get('calories', 0)),
            'protein': float(result.get('protein', 0)),
            'carbs': float(result.get('carbs', 0)),
            'fat': float(result.get('fat', 0)),
            'basis': result.get('basis', ''),
        }
    except Exception as e:
        logger.error(f"OpenRouter API image error: {e}")
        return {'food_name': None, 'calories': None, 'protein': None, 'carbs': None, 'fat': None, 'basis': ''}


def parse_and_estimate_foods(text):
    """
    Parse free-form text describing foods and estimate nutrition for each.
    Returns a list of dicts, or None on failure.
    """
    if not OPENROUTER_API_KEY:
        logger.warning("OPEN_ROUTER_ID not set, cannot parse foods")
        return None

    prompt = parse_foods_prompt(text)

    try:
        messages = [{'role': 'user', 'content': prompt}]
        response_text = _openrouter_request(messages, TEXT_MODELS)
        result = _parse_response_json(response_text)
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
        logger.error(f"OpenRouter API error for parse_and_estimate_foods: {e}")
        return None


def modify_food_estimation(original_food, modification):
    """
    Re-estimate nutrition for an existing food entry based on user's modification.
    Returns dict with keys: name, description, calories, protein, carbs, fat, basis.
    Returns None on failure.
    """
    if not OPENROUTER_API_KEY:
        return None

    desc = original_food.get('description', '')
    original_desc = f"{original_food['name']} ({desc})" if desc else original_food['name']
    original_nutrition = (
        f"{original_food.get('calories', 0):.0f} kcal, "
        f"{original_food.get('protein', 0):.1f}g protein, "
        f"{original_food.get('carbs', 0):.1f}g carbs, "
        f"{original_food.get('fat', 0):.1f}g fat"
    )

    prompt = modify_food_prompt(original_desc, original_nutrition, original_food.get('basis', ''), modification)

    try:
        messages = [{'role': 'user', 'content': prompt}]
        text = _openrouter_request(messages, TEXT_MODELS)
        result = _parse_response_json(text)
        return {
            'name': result.get('name', original_food['name']),
            'description': result.get('description', ''),
            'calories': float(result.get('calories', 0)),
            'protein': float(result.get('protein', 0)),
            'carbs': float(result.get('carbs', 0)),
            'fat': float(result.get('fat', 0)),
            'basis': result.get('basis', ''),
        }
    except Exception as e:
        logger.error(f"OpenRouter API error for modify_food_estimation: {e}")
        return None


def generate_diet_advice(foods, tdee=None, user_prompt='', goal=''):
    """
    Ask OpenRouter for dietary advice based on today's food log.
    Returns advice string, or None on failure.
    """
    if not OPENROUTER_API_KEY:
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
        tdee_info = f"\nUser's TDEE target: {tdee} kcal/day. Remaining budget: {remaining:.0f} kcal."
    if goal:
        tdee_info += f"\nUser's goal: {goal} (增肌=bulk/gain muscle, 維持=maintain, 減脂=cut/lose fat)."

    if user_prompt:
        question = user_prompt
    else:
        question = "Give brief dietary advice based on today's intake and the user's goal. What's missing? What should I eat next? Keep it concise (under 200 characters)."

    prompt = diet_advice_prompt(food_list, total_cal, tdee_info, question)

    try:
        messages = [{'role': 'user', 'content': prompt}]
        return _openrouter_request(messages, TEXT_MODELS)
    except Exception as e:
        logger.error(f"OpenRouter diet advice error: {e}")
        return None
