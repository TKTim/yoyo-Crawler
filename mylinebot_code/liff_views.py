"""
LIFF (LINE Frontend Framework) web editor views.
Serves the editor page and REST API for food entry CRUD.
"""
import json
import logging

import requests as http_requests
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .dietary_storage import (
    get_entries_with_ids,
    update_entry_by_id,
    delete_entry_by_id,
    add_entry_for_date,
)
from .gemini_api import parse_and_estimate_foods, modify_food_estimation, estimate_nutrition_from_image

logger = logging.getLogger(__name__)


def _get_liff_user_id(request):
    """
    Validate LIFF access token via LINE Profile API.
    Returns user_id string, or None if invalid/missing.
    """
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None

    token = auth[7:]
    try:
        resp = http_requests.get(
            'https://api.line.me/v2/profile',
            headers={'Authorization': f'Bearer {token}'},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"LIFF token validation failed: {resp.status_code}")
            return None
        return resp.json().get('userId')
    except Exception as e:
        logger.error(f"LIFF token validation error: {e}")
        return None


def _json_error(msg, status=400):
    return JsonResponse({'status': 'error', 'message': msg}, status=status)


# ── Page view ──────────────────────────────────────────────────────────────────

def liff_editor(request):
    """Render the LIFF editor HTML page."""
    return render(request, 'liff_editor.html', {
        'liff_id': settings.LIFF_ID,
        'mode': request.GET.get('mode', ''),
    })


# ── API views ──────────────────────────────────────────────────────────────────

@csrf_exempt
def api_entries(request):
    """
    GET  → list entries for authenticated user (last 7 days)
    POST → add a new entry
    """
    user_id = _get_liff_user_id(request)
    if not user_id:
        return _json_error('Unauthorized', 401)

    if request.method == 'GET':
        data = get_entries_with_ids(user_id)
        return JsonResponse({'status': 'ok', 'data': data})

    if request.method == 'POST':
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return _json_error('Invalid JSON')

        date_str = body.get('date')
        if not date_str:
            return _json_error('Missing "date" field')

        entry = add_entry_for_date(user_id, date_str, body)
        return JsonResponse({'status': 'ok', 'entry': entry}, status=201)

    return _json_error('Method not allowed', 405)


@csrf_exempt
def api_entry_detail(request, entry_id):
    """
    PUT    → update an entry
    DELETE → delete an entry
    """
    user_id = _get_liff_user_id(request)
    if not user_id:
        return _json_error('Unauthorized', 401)

    if request.method == 'PUT':
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return _json_error('Invalid JSON')

        updated = update_entry_by_id(entry_id, user_id, body)
        if not updated:
            return _json_error('Entry not found', 404)
        return JsonResponse({'status': 'ok', 'entry': updated})

    if request.method == 'DELETE':
        removed = delete_entry_by_id(entry_id, user_id)
        if not removed:
            return _json_error('Entry not found', 404)
        return JsonResponse({'status': 'ok'})

    return _json_error('Method not allowed', 405)


@csrf_exempt
def api_ai_add(request):
    """
    POST → parse food description with AI, estimate nutrition, save entries.
    Body: {"text": "一碗滷肉飯和一杯豆漿", "date": "2026-03-26"}
    """
    if request.method != 'POST':
        return _json_error('Method not allowed', 405)

    user_id = _get_liff_user_id(request)
    if not user_id:
        return _json_error('Unauthorized', 401)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _json_error('Invalid JSON')

    text = body.get('text', '').strip()
    date_str = body.get('date', '')
    if not text:
        return _json_error('Missing "text" field')
    if not date_str:
        return _json_error('Missing "date" field')

    foods = parse_and_estimate_foods(text)
    if not foods:
        return _json_error('AI 無法辨識食物，請再試一次', 422)

    saved = []
    for food in foods:
        entry = add_entry_for_date(user_id, date_str, food)
        saved.append(entry)

    return JsonResponse({'status': 'ok', 'entries': saved}, status=201)


@csrf_exempt
def api_ai_modify(request, entry_id):
    """POST → AI re-estimate an entry based on modification text."""
    if request.method != 'POST':
        return _json_error('Method not allowed', 405)

    user_id = _get_liff_user_id(request)
    if not user_id:
        return _json_error('Unauthorized', 401)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return _json_error('Invalid JSON')

    text = body.get('text', '').strip()
    if not text:
        return _json_error('Missing "text" field')

    # Fetch current entry
    from .models import FoodEntry
    entry = FoodEntry.objects.filter(id=entry_id, user_id=user_id).first()
    if not entry:
        return _json_error('Entry not found', 404)

    original = {
        'name': entry.name,
        'description': entry.description,
        'calories': entry.calories or 0,
        'protein': entry.protein or 0,
        'carbs': entry.carbs or 0,
        'fat': entry.fat or 0,
        'basis': entry.basis or '',
    }

    result = modify_food_estimation(original, text)
    if not result:
        return _json_error('AI 無法處理修改，請再試一次', 422)

    updated = update_entry_by_id(entry_id, user_id, result)
    return JsonResponse({'status': 'ok', 'entry': updated})


@csrf_exempt
def api_image_add(request):
    """POST → estimate nutrition from uploaded food photo, save entry."""
    if request.method != 'POST':
        return _json_error('Method not allowed', 405)

    user_id = _get_liff_user_id(request)
    if not user_id:
        return _json_error('Unauthorized', 401)

    image_file = request.FILES.get('image')
    if not image_file:
        return _json_error('Missing image file')

    date_str = request.POST.get('date', '')
    if not date_str:
        return _json_error('Missing "date" field')

    image_bytes = image_file.read()
    mime_type = image_file.content_type or 'image/jpeg'

    result = estimate_nutrition_from_image(image_bytes, mime_type)
    if not result.get('food_name'):
        return _json_error('AI 無法辨識食物，請再試一次', 422)

    food_entry = {
        'name': result['food_name'],
        'description': '',
        'calories': result.get('calories'),
        'protein': result.get('protein'),
        'carbs': result.get('carbs'),
        'fat': result.get('fat'),
        'basis': result.get('basis', ''),
    }

    entry = add_entry_for_date(user_id, date_str, food_entry)
    return JsonResponse({'status': 'ok', 'entry': entry}, status=201)
