"""
Gist-based storage for dietary logs.
Each user's food entries are stored per-date in a single Gist JSON file.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get('GITHUB_GIST_TOKEN', '')
GIST_ID = os.environ.get('GIST_ID', '')
GIST_DIETARY_FILENAME = 'yoyo_dietary_logs.json'

# Taiwan timezone (UTC+8)
TW_TZ = timezone(timedelta(hours=8))

# In-memory store: { "user_id": { "2026-03-17": { "foods": [...] } } }
_dietary_logs = {}


def _today_str():
    """Get today's date string in Taiwan timezone."""
    return datetime.now(TW_TZ).strftime('%Y-%m-%d')


def _now_str():
    """Get current timestamp string in Taiwan timezone."""
    return datetime.now(TW_TZ).strftime('%Y-%m-%dT%H:%M:%S')


def load_dietary_logs():
    """Load dietary logs from Gist into in-memory dict."""
    global _dietary_logs
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured, skipping dietary logs load")
        return False

    try:
        response = requests.get(
            f'https://api.github.com/gists/{GIST_ID}',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json',
            },
            timeout=30
        )
        response.raise_for_status()

        gist_data = response.json()
        file_content = gist_data.get('files', {}).get(GIST_DIETARY_FILENAME, {}).get('content', '{}')
        _dietary_logs = json.loads(file_content)
        logger.info(f"Loaded dietary logs for {len(_dietary_logs)} users from Gist")
        return True
    except Exception as e:
        logger.error(f"Failed to load dietary logs from Gist: {e}")
        return False


def save_dietary_logs():
    """Save in-memory dietary logs to Gist. Prunes old entries first."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured, skipping dietary logs save")
        return False

    prune_old_entries()

    content = json.dumps(_dietary_logs, ensure_ascii=False, indent=2)

    try:
        response = requests.patch(
            f'https://api.github.com/gists/{GIST_ID}',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json',
            },
            json={
                'files': {
                    GIST_DIETARY_FILENAME: {'content': content}
                }
            },
            timeout=30
        )
        response.raise_for_status()
        logger.info("Saved dietary logs to Gist")
        return True
    except Exception as e:
        logger.error(f"Failed to save dietary logs to Gist: {e}")
        return False


def add_food_entry(user_id, food_entry):
    """
    Append a food entry to today's log for a user, then save to Gist.
    food_entry: dict with keys name, description, calories, protein, carbs, fat
    Returns True on success, False on Gist save failure.
    """
    today = _today_str()

    if user_id not in _dietary_logs:
        _dietary_logs[user_id] = {}
    if today not in _dietary_logs[user_id]:
        _dietary_logs[user_id][today] = {'foods': []}

    food_entry['added_at'] = _now_str()
    _dietary_logs[user_id][today]['foods'].append(food_entry)

    return save_dietary_logs()


def remove_food_entry(user_id, index):
    """
    Remove a food entry by 1-based index from today's log.
    Returns the removed food dict on success, None if index is invalid.
    """
    today = _today_str()
    foods = _dietary_logs.get(user_id, {}).get(today, {}).get('foods', [])

    if not foods or index < 1 or index > len(foods):
        return None

    removed = foods.pop(index - 1)
    save_dietary_logs()
    return removed


def get_today_log(user_id):
    """Return today's food list for a user, or empty list."""
    today = _today_str()
    return _dietary_logs.get(user_id, {}).get(today, {}).get('foods', [])


def get_all_users_today():
    """Return dict of {user_id: [foods]} for all users with entries today."""
    today = _today_str()
    result = {}
    for user_id, dates in _dietary_logs.items():
        foods = dates.get(today, {}).get('foods', [])
        if foods:
            result[user_id] = foods
    return result


def prune_old_entries():
    """Remove entries older than 7 days for all users."""
    cutoff = (datetime.now(TW_TZ) - timedelta(days=7)).strftime('%Y-%m-%d')
    for user_id in list(_dietary_logs.keys()):
        dates = _dietary_logs[user_id]
        old_dates = [d for d in dates if d < cutoff]
        for d in old_dates:
            del dates[d]
        # Remove user entirely if no dates left
        if not dates:
            del _dietary_logs[user_id]
