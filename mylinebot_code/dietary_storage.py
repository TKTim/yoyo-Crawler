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


def add_food_entries(user_id, food_entries):
    """
    Batch-insert multiple food entries to today's log, then sync to Gist once.
    food_entries: list of dicts with keys name, calories, protein, carbs, fat, basis
    Returns True on success.
    """
    from .models import FoodEntry
    from .gist_storage import save_dietary_to_gist

    today = _today_date()
    objects = [
        FoodEntry(
            user_id=user_id,
            date=today,
            name=entry.get('name', ''),
            description=entry.get('description', ''),
            calories=entry.get('calories'),
            protein=entry.get('protein'),
            carbs=entry.get('carbs'),
            fat=entry.get('fat'),
            basis=entry.get('basis', ''),
        )
        for entry in food_entries
    ]
    FoodEntry.objects.bulk_create(objects)

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


def remove_food_entries(user_id, indices):
    """
    Remove multiple food entries by 1-based indices from today's log.
    Indices are processed in descending order so earlier indices stay valid.
    Returns list of removed food dicts. Invalid indices are skipped.
    """
    from .models import FoodEntry
    from .gist_storage import save_dietary_to_gist

    today = _today_date()
    entries = list(FoodEntry.objects.filter(user_id=user_id, date=today).order_by('added_at'))

    if not entries:
        return []

    removed = []
    for index in sorted(set(indices), reverse=True):
        if index < 1 or index > len(entries):
            continue
        entry = entries[index - 1]
        removed.append(_entry_to_dict(entry))
        entry.delete()

    if removed:
        save_dietary_to_gist()

    removed.reverse()  # return in original index order
    return removed


def get_food_entry_by_index(user_id, index):
    """
    Get a food entry by 1-based index from today's log.
    Returns the food dict on success, None if index is invalid.
    """
    from .models import FoodEntry

    today = _today_date()
    entries = list(FoodEntry.objects.filter(user_id=user_id, date=today).order_by('added_at'))

    if not entries or index < 1 or index > len(entries):
        return None

    return _entry_to_dict(entries[index - 1])


def update_food_entry(user_id, index, updated_food):
    """
    Update a food entry by 1-based index from today's log, then sync to Gist.
    updated_food: dict with keys name, description, calories, protein, carbs, fat, basis
    Returns True on success, False if index is invalid.
    """
    from .models import FoodEntry
    from .gist_storage import save_dietary_to_gist

    today = _today_date()
    entries = list(FoodEntry.objects.filter(user_id=user_id, date=today).order_by('added_at'))

    if not entries or index < 1 or index > len(entries):
        return False

    entry = entries[index - 1]
    entry.name = updated_food.get('name', entry.name)
    entry.description = updated_food.get('description', entry.description)
    entry.calories = updated_food.get('calories', entry.calories)
    entry.protein = updated_food.get('protein', entry.protein)
    entry.carbs = updated_food.get('carbs', entry.carbs)
    entry.fat = updated_food.get('fat', entry.fat)
    entry.basis = updated_food.get('basis', entry.basis)
    entry.save()

    save_dietary_to_gist()
    return True


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


def _entry_to_dict_with_id(entry):
    """Convert a FoodEntry to dict including the Django PK (for LIFF editor)."""
    d = _entry_to_dict(entry)
    d['id'] = entry.id
    return d


def get_entries_with_ids(user_id, days=7):
    """Return {date_str: [entry dicts with id]} for the last N days, newest first."""
    from .models import FoodEntry

    cutoff = _today_date() - timedelta(days=days)
    entries = FoodEntry.objects.filter(
        user_id=user_id, date__gte=cutoff,
    ).order_by('-date', 'added_at')

    result = defaultdict(list)
    for entry in entries:
        result[entry.date.isoformat()].append(_entry_to_dict_with_id(entry))

    return dict(sorted(result.items(), reverse=True))


def update_entry_by_id(entry_id, user_id, updated_fields):
    """
    Update a FoodEntry by its primary key. Verifies user_id ownership.
    Returns the updated dict, or None if not found / wrong user.
    """
    from .models import FoodEntry
    from .gist_storage import save_dietary_to_gist

    entry = FoodEntry.objects.filter(id=entry_id, user_id=user_id).first()
    if not entry:
        return None

    for field in ('name', 'description', 'calories', 'protein', 'carbs', 'fat', 'basis'):
        if field in updated_fields:
            setattr(entry, field, updated_fields[field])
    entry.save()

    save_dietary_to_gist()
    return _entry_to_dict_with_id(entry)


def delete_entry_by_id(entry_id, user_id):
    """
    Delete a FoodEntry by its primary key. Verifies user_id ownership.
    Returns the removed dict, or None if not found / wrong user.
    """
    from .models import FoodEntry
    from .gist_storage import save_dietary_to_gist

    entry = FoodEntry.objects.filter(id=entry_id, user_id=user_id).first()
    if not entry:
        return None

    removed = _entry_to_dict_with_id(entry)
    entry.delete()

    save_dietary_to_gist()
    return removed


def add_entry_for_date(user_id, date_str, food_entry):
    """
    Add a food entry for a specific date (not just today).
    date_str: ISO format date string (e.g. '2026-03-25')
    Returns the created entry dict with id.
    """
    from datetime import date as date_type
    from .models import FoodEntry
    from .gist_storage import save_dietary_to_gist

    entry = FoodEntry.objects.create(
        user_id=user_id,
        date=date_type.fromisoformat(date_str),
        name=food_entry.get('name', ''),
        description=food_entry.get('description', ''),
        calories=food_entry.get('calories'),
        protein=food_entry.get('protein'),
        carbs=food_entry.get('carbs'),
        fat=food_entry.get('fat'),
        basis=food_entry.get('basis', ''),
    )

    save_dietary_to_gist()
    return _entry_to_dict_with_id(entry)


def prune_old_entries():
    """Remove entries older than 7 days."""
    from .models import FoodEntry

    cutoff = _today_date() - timedelta(days=7)
    deleted, _ = FoodEntry.objects.filter(date__lt=cutoff).delete()
    if deleted:
        logger.info(f"Pruned {deleted} old food entries")
