"""
DB-primary storage for dietary logs, with Gist write-through backup.
Each user's food entries are stored per-date in the FoodEntry model.
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Taiwan timezone (UTC+8)
TW_TZ = timezone(timedelta(hours=8))


def _today_date():
    """Get today's date object in Taiwan timezone."""
    return datetime.now(TW_TZ).date()


def _entry_to_dict(entry):
    """Convert a FoodEntry model instance to the dict format views.py expects."""
    return {
        'name': entry.name,
        'description': entry.description,
        'calories': entry.calories,
        'protein': entry.protein,
        'carbs': entry.carbs,
        'fat': entry.fat,
        'basis': entry.basis,
        'added_at': entry.added_at.astimezone(TW_TZ).strftime('%Y-%m-%dT%H:%M:%S') if entry.added_at else '',
    }


def add_food_entry(user_id, food_entry):
    """
    Append a food entry to today's log for a user, then sync to Gist.
    food_entry: dict with keys name, description, calories, protein, carbs, fat
    Returns True on success.
    """
    from .models import FoodEntry
    from .gist_storage import save_dietary_to_gist

    FoodEntry.objects.create(
        user_id=user_id,
        date=_today_date(),
        name=food_entry.get('name', ''),
        description=food_entry.get('description', ''),
        calories=food_entry.get('calories'),
        protein=food_entry.get('protein'),
        carbs=food_entry.get('carbs'),
        fat=food_entry.get('fat'),
        basis=food_entry.get('basis', ''),
    )

    save_dietary_to_gist()
    return True


def remove_food_entry(user_id, index):
    """
    Remove a food entry by 1-based index from today's log.
    Returns the removed food dict on success, None if index is invalid.
    """
    from .models import FoodEntry
    from .gist_storage import save_dietary_to_gist

    today = _today_date()
    entries = list(FoodEntry.objects.filter(user_id=user_id, date=today).order_by('added_at'))

    if not entries or index < 1 or index > len(entries):
        return None

    entry = entries[index - 1]
    removed = _entry_to_dict(entry)
    entry.delete()

    save_dietary_to_gist()
    return removed


def get_today_log(user_id):
    """Return today's food list for a user, or empty list."""
    from .models import FoodEntry

    today = _today_date()
    entries = FoodEntry.objects.filter(user_id=user_id, date=today).order_by('added_at')
    return [_entry_to_dict(e) for e in entries]


def get_history(user_id):
    """Return dict of {date: foods} for all dates the user has data, sorted newest first."""
    from .models import FoodEntry

    entries = FoodEntry.objects.filter(user_id=user_id).order_by('-date', 'added_at')
    result = defaultdict(list)
    for entry in entries:
        result[entry.date.isoformat()].append(_entry_to_dict(entry))

    return dict(sorted(result.items(), reverse=True))


def get_all_users_today():
    """Return dict of {user_id: [foods]} for all users with entries today."""
    from .models import FoodEntry

    today = _today_date()
    entries = FoodEntry.objects.filter(date=today).order_by('added_at')

    result = defaultdict(list)
    for entry in entries:
        result[entry.user_id].append(_entry_to_dict(entry))

    return dict(result)


def set_tdee(user_id, tdee):
    """Set TDEE for a user and sync to Gist."""
    from .models import UserTdee
    from .gist_storage import save_dietary_to_gist

    UserTdee.objects.update_or_create(
        user_id=user_id,
        defaults={'tdee': tdee},
    )

    save_dietary_to_gist()
    return True


def get_tdee(user_id):
    """Get TDEE for a user, or None if not set."""
    from .models import UserTdee

    obj = UserTdee.objects.filter(user_id=user_id).first()
    return obj.tdee if obj else None


def prune_old_entries():
    """Remove entries older than 7 days."""
    from .models import FoodEntry

    cutoff = _today_date() - timedelta(days=7)
    deleted, _ = FoodEntry.objects.filter(date__lt=cutoff).delete()
    if deleted:
        logger.info(f"Pruned {deleted} old food entries")
