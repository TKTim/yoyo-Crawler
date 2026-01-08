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


def save_articles_to_gist():
    """Save all articles from DB to GitHub Gist."""
    if not GITHUB_TOKEN or not GIST_ID:
        logger.warning("Gist storage not configured (missing GITHUB_GIST_TOKEN or GIST_ID)")
        return False

    from .models import ParsedArticle

    articles = list(ParsedArticle.objects.all().values('title', 'url', 'post_date'))

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

    from .models import ParsedArticle

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
                }
            )
            if created:
                loaded += 1

        logger.info(f"Loaded {loaded} articles from Gist into DB")
        return True
    except Exception as e:
        logger.error(f"Failed to load from Gist: {e}")
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
