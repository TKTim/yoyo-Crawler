import re
import logging
from datetime import datetime, date
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup

from .models import ParsedArticle

# Setup logging
logger = logging.getLogger(__name__)

FORUM_URL = "https://yoyo.club.tw/viewforum.php?f=2"
BASE_URL = "https://yoyo.club.tw/"


def parse_forum():
    """
    Parse the forum and save new articles.
    Date is extracted from article title (e.g., "12/9 (Tue.) Topic Name").

    Returns:
        list of newly saved ParsedArticle objects
    """
    logger.info("Parsing forum...")
    headers = {
        'User-Agent': 'YoYo-Bot/1.0',
        'X-Bot-Secret': 'yoyo2025scraper'  # Cloudflare can check this
    }
    response = requests.get(FORUM_URL, headers=headers, timeout=30)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, 'html.parser')

    new_articles = []

    # Find all topic rows - phpBB forum structure
    topic_rows = soup.select('li.row')

    for row in topic_rows:
        # Get article title and URL
        title_link = row.select_one('a.topictitle')
        if not title_link:
            continue

        title = title_link.get_text(strip=True)
        raw_url = urljoin(BASE_URL, title_link.get('href', ''))
        url = clean_url(raw_url)  # Remove session ID

        # Parse date from title (format: "12/9 (Tue.) Topic Name")
        post_date = parse_date_from_title(title)

        if post_date is None:
            # Skip articles without date in title
            continue

        # Check if already in database
        if ParsedArticle.objects.filter(url=url).exists():
            continue

        # Save new article
        article = ParsedArticle.objects.create(
            title=title,
            url=url,
            post_date=post_date
        )
        new_articles.append(article)
        logger.info(f"NEW ARTICLE | Date: {post_date} | Title: {title} | URL: {url}")

    logger.info(f"Parsing complete. Found {len(new_articles)} new article(s)")

    # Keep only the 20 newest articles
    cleanup_old_articles(keep=20)

    return new_articles


def cleanup_old_articles(keep=20):
    """
    Remove old articles, keeping only the newest ones.
    """
    total = ParsedArticle.objects.count()
    if total > keep:
        # Get IDs of articles to keep (newest by post_date)
        keep_ids = ParsedArticle.objects.order_by('-post_date')[:keep].values_list('id', flat=True)
        # Delete the rest
        deleted, _ = ParsedArticle.objects.exclude(id__in=list(keep_ids)).delete()
        logger.info(f"Cleanup: deleted {deleted} old article(s), kept {keep}")


def parse_date_from_title(title):
    """
    Parse date from article title.
    Format: "12/9 (Tue.) Topic Name" or "1/15 (Wed.) Topic Name"

    Returns date object or None if not found.
    """
    # Pattern: month/day followed by (weekday)
    pattern = r'^(\d{1,2})/(\d{1,2})\s*\([A-Za-z]+\.?\)'
    match = re.match(pattern, title)

    if not match:
        return None

    month = int(match.group(1))
    day = int(match.group(2))

    # Determine year based on current date
    today = date.today()
    year = today.year

    # If the month is way ahead (e.g., it's December and we see January),
    # it's probably next year
    if month < today.month - 6:
        year += 1
    # If the month is way behind (e.g., it's January and we see December),
    # it's probably last year
    elif month > today.month + 6:
        year -= 1

    try:
        return date(year, month, day)
    except ValueError:
        return None


def clean_url(url):
    """Remove session ID (sid) from URL to avoid duplicates."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    # Remove sid parameter
    params.pop('sid', None)
    # Rebuild URL without sid
    clean_query = urlencode(params, doseq=True)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{clean_query}" if clean_query else f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def get_week_articles():
    """Get articles for current week from database."""
    from datetime import timedelta

    today = date.today()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    sunday = monday + timedelta(days=6)

    return ParsedArticle.objects.filter(
        post_date__gte=monday,
        post_date__lte=sunday
    ).order_by('post_date')
