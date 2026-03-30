"""
GitHub Gist storage for persistent article data.
Workaround for Render's ephemeral filesystem wiping SQLite DB.
"""
import json
import logging
import os
from datetime import date

import requests

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get('GITHUB_GIST_TOKEN', '')
GIST_ID = os.environ.get('GIST_ID', '')
GIST_FILENAME = 'yoyo_articles.json'
GIST_USERS_FILENAME = 'yoyo_authorized_users.json'
GIST_TARGETS_FILENAME = 'yoyo_push_targets.json'
GIST_DIETARY_FILENAME = 'yoyo_dietary_logs.json'
GIST_PROFILES_FILENAME = 'yoyo_user_profiles.json'


def save_articles_to_gist():
    """Save all articles from DB to GitHub Gist."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from .models import ParsedArticle

    articles = list(ParsedArticle.objects.all().values('title', 'url', 'post_date', 'author'))

    # Convert dates to strings for JSON
    for article in articles:
        article['post_date'] = article['post_date'].isoformat()

    content = json.dumps(articles, ensure_ascii=False, indent=2)

    try:
        response = requests.patch(
            f'https://api.github.com/gists/{GIST_ID}',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json',
            },
            json={
                'files': {
                    GIST_FILENAME: {'content': content}
                }
            },
            timeout=30
        )
        response.raise_for_status()
        logger.info(f"Saved {len(articles)} articles to Gist")
        return True
    except Exception as e:
        logger.error(f"Failed to save to Gist: {e}")
        return False


def load_articles_from_gist():
    """Load articles from GitHub Gist into DB."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from django.db import connection
    from .models import ParsedArticle

    # Check if the table exists before querying (migrations may not have run yet)
    table_name = ParsedArticle._meta.db_table
    if table_name not in connection.introspection.table_names():
        logger.warning(f"Table '{table_name}' does not exist yet, skipping Gist load")
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
        file_content = gist_data.get('files', {}).get(GIST_FILENAME, {}).get('content', '[]')
        articles = json.loads(file_content)

        # Skip if DB already has data (avoid overwriting during normal operation)
        if ParsedArticle.objects.exists():
            logger.info(f"DB already has {ParsedArticle.objects.count()} articles, skipping Gist load")
            return True

        loaded = 0
        for article in articles:
            post_date = date.fromisoformat(article['post_date'])
            _, created = ParsedArticle.objects.get_or_create(
                url=article['url'],
                defaults={
                    'title': article['title'],
                    'post_date': post_date,
                    'author': article.get('author', ''),
                }
            )
            if created:
                loaded += 1

        logger.info(f"Loaded {loaded} articles from Gist into DB")
        return True
    except Exception as e:
        logger.error(f"Failed to load from Gist: {e}")
        return False


def save_users_to_gist():
    """Save all authorized users from DB to GitHub Gist."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from .models import AuthorizedUser

    users = list(AuthorizedUser.objects.all().values('user_id', 'label'))
    content = json.dumps(users, ensure_ascii=False, indent=2)

    try:
        response = requests.patch(
            f'https://api.github.com/gists/{GIST_ID}',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json',
            },
            json={
                'files': {
                    GIST_USERS_FILENAME: {'content': content}
                }
            },
            timeout=30
        )
        response.raise_for_status()
        logger.info(f"Saved {len(users)} authorized users to Gist")
        return True
    except Exception as e:
        logger.error(f"Failed to save users to Gist: {e}")
        return False


def load_users_from_gist():
    """Load authorized users from GitHub Gist into DB."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from django.db import connection
    from .models import AuthorizedUser

    table_name = AuthorizedUser._meta.db_table
    if table_name not in connection.introspection.table_names():
        logger.warning(f"Table '{table_name}' does not exist yet, skipping Gist load")
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
        file_content = gist_data.get('files', {}).get(GIST_USERS_FILENAME, {}).get('content', '[]')
        users = json.loads(file_content)

        if AuthorizedUser.objects.exists():
            logger.info(f"DB already has {AuthorizedUser.objects.count()} authorized users, skipping Gist load")
            return True

        loaded = 0
        for user in users:
            _, created = AuthorizedUser.objects.get_or_create(
                user_id=user['user_id'],
                defaults={'label': user.get('label', '')}
            )
            if created:
                loaded += 1

        logger.info(f"Loaded {loaded} authorized users from Gist into DB")
        return True
    except Exception as e:
        logger.error(f"Failed to load users from Gist: {e}")
        return False


def save_targets_to_gist():
    """Save all push targets from DB to GitHub Gist."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from .models import PushTarget

    targets = list(PushTarget.objects.all().values('target_id', 'label'))
    content = json.dumps(targets, ensure_ascii=False, indent=2)

    try:
        response = requests.patch(
            f'https://api.github.com/gists/{GIST_ID}',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json',
            },
            json={
                'files': {
                    GIST_TARGETS_FILENAME: {'content': content}
                }
            },
            timeout=30
        )
        response.raise_for_status()
        logger.info(f"Saved {len(targets)} push targets to Gist")
        return True
    except Exception as e:
        logger.error(f"Failed to save push targets to Gist: {e}")
        return False


def load_targets_from_gist():
    """Load push targets from GitHub Gist into DB."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from django.db import connection
    from .models import PushTarget

    table_name = PushTarget._meta.db_table
    if table_name not in connection.introspection.table_names():
        logger.warning(f"Table '{table_name}' does not exist yet, skipping Gist load")
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
        file_content = gist_data.get('files', {}).get(GIST_TARGETS_FILENAME, {}).get('content', '[]')
        targets = json.loads(file_content)

        if PushTarget.objects.exists():
            logger.info(f"DB already has {PushTarget.objects.count()} push targets, skipping Gist load")
            return True

        loaded = 0
        for target in targets:
            _, created = PushTarget.objects.get_or_create(
                target_id=target['target_id'],
                defaults={'label': target.get('label', '')}
            )
            if created:
                loaded += 1

        logger.info(f"Loaded {loaded} push targets from Gist into DB")
        return True
    except Exception as e:
        logger.error(f"Failed to load push targets from Gist: {e}")
        return False


def save_dietary_to_gist():
    """Save all FoodEntry + UserTdee records from DB to Gist as JSON backup."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from collections import defaultdict
    from .models import FoodEntry, UserTdee
    from .dietary_storage import prune_old_entries

    prune_old_entries()

    # Build the same JSON structure as the old in-memory dict:
    # { "user_id": { "tdee": 2000, "2026-03-17": { "foods": [...] } } }
    data = defaultdict(dict)

    for tdee_obj in UserTdee.objects.all():
        data[tdee_obj.user_id]['tdee'] = tdee_obj.tdee

    for entry in FoodEntry.objects.all().order_by('added_at'):
        date_str = entry.date.isoformat()
        user_data = data[entry.user_id]
        if date_str not in user_data:
            user_data[date_str] = {'foods': []}
        user_data[date_str]['foods'].append({
            'name': entry.name,
            'description': entry.description,
            'calories': entry.calories,
            'protein': entry.protein,
            'carbs': entry.carbs,
            'fat': entry.fat,
            'basis': entry.basis,
            'added_at': entry.added_at.strftime('%Y-%m-%dT%H:%M:%S') if entry.added_at else '',
        })

    content = json.dumps(dict(data), ensure_ascii=False, indent=2)

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


def load_dietary_from_gist():
    """Load dietary logs from Gist into DB. Only restores if DB tables are empty."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from django.db import connection
    from .models import FoodEntry, UserTdee

    # Check tables exist
    tables = connection.introspection.table_names()
    for model in (FoodEntry, UserTdee):
        table_name = model._meta.db_table
        if table_name not in tables:
            logger.warning(f"Table '{table_name}' does not exist yet, skipping dietary Gist load")
            return False

    # Skip if DB already has data
    if FoodEntry.objects.exists() or UserTdee.objects.exists():
        logger.info("DB already has dietary data, skipping Gist load")
        return True

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
        dietary_data = json.loads(file_content)

        loaded_foods = 0
        loaded_tdee = 0

        for user_id, user_data in dietary_data.items():
            # Restore TDEE
            if 'tdee' in user_data:
                UserTdee.objects.get_or_create(
                    user_id=user_id,
                    defaults={'tdee': user_data['tdee']},
                )
                loaded_tdee += 1

            # Restore food entries
            for key, value in user_data.items():
                if key == 'tdee':
                    continue
                date_obj = date.fromisoformat(key)
                for food in value.get('foods', []):
                    FoodEntry.objects.create(
                        user_id=user_id,
                        date=date_obj,
                        name=food.get('name', ''),
                        description=food.get('description', ''),
                        calories=food.get('calories'),
                        protein=food.get('protein'),
                        carbs=food.get('carbs'),
                        fat=food.get('fat'),
                        basis=food.get('basis', ''),
                    )
                    loaded_foods += 1

        logger.info(f"Loaded {loaded_foods} food entries and {loaded_tdee} TDEE settings from Gist into DB")
        return True
    except Exception as e:
        logger.error(f"Failed to load dietary logs from Gist: {e}")
        return False


def save_profiles_to_gist():
    """Save all user profiles from DB to GitHub Gist."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from .models import UserProfile

    profiles = list(UserProfile.objects.all().values(
        'user_id', 'gender', 'height', 'weight', 'age', 'activity_level', 'goal',
        'streak_count', 'streak_last_date',
    ))
    # Convert dates to strings for JSON
    for profile in profiles:
        if profile.get('streak_last_date'):
            profile['streak_last_date'] = profile['streak_last_date'].isoformat()
    content = json.dumps(profiles, ensure_ascii=False, indent=2)

    try:
        response = requests.patch(
            f'https://api.github.com/gists/{GIST_ID}',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json',
            },
            json={
                'files': {
                    GIST_PROFILES_FILENAME: {'content': content}
                }
            },
            timeout=30
        )
        response.raise_for_status()
        logger.info(f"Saved {len(profiles)} user profiles to Gist")
        return True
    except Exception as e:
        logger.error(f"Failed to save profiles to Gist: {e}")
        return False


def load_profiles_from_gist():
    """Load user profiles from GitHub Gist into DB."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from django.db import connection
    from .models import UserProfile

    table_name = UserProfile._meta.db_table
    if table_name not in connection.introspection.table_names():
        logger.warning(f"Table '{table_name}' does not exist yet, skipping profiles Gist load")
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
        file_content = gist_data.get('files', {}).get(GIST_PROFILES_FILENAME, {}).get('content', '[]')
        profiles = json.loads(file_content)

        if UserProfile.objects.exists():
            logger.info(f"DB already has {UserProfile.objects.count()} user profiles, skipping Gist load")
            return True

        loaded = 0
        for p in profiles:
            streak_last_date = None
            if p.get('streak_last_date'):
                streak_last_date = date.fromisoformat(p['streak_last_date'])

            _, created = UserProfile.objects.get_or_create(
                user_id=p['user_id'],
                defaults={
                    'gender': p.get('gender', ''),
                    'height': p.get('height', 0),
                    'weight': p.get('weight', 0),
                    'age': p.get('age', 0),
                    'activity_level': p.get('activity_level', ''),
                    'goal': p.get('goal', ''),
                    'streak_count': p.get('streak_count', 0),
                    'streak_last_date': streak_last_date,
                },
            )
            if created:
                loaded += 1

        logger.info(f"Loaded {loaded} user profiles from Gist into DB")
        return True
    except Exception as e:
        logger.error(f"Failed to load profiles from Gist: {e}")
        return False


def create_gist():
    """Create a new Gist for article storage. Run once to get GIST_ID."""
    if not GITHUB_TOKEN:
        print("Error: GITHUB_GIST_TOKEN not set")
        return None

    try:
        response = requests.post(
            'https://api.github.com/gists',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json',
            },
            json={
                'description': 'YoYo English Bot - Article Storage',
                'public': False,
                'files': {
                    GIST_FILENAME: {'content': '[]'}
                }
            },
            timeout=30
        )
        response.raise_for_status()
        gist_id = response.json()['id']
        print(f"Created Gist! Add this to your environment:")
        print(f"GIST_ID={gist_id}")
        return gist_id
    except Exception as e:
        print(f"Failed to create Gist: {e}")
        return None
