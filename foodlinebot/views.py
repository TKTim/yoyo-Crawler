import logging
from datetime import date, timedelta

from django.conf import settings

logger = logging.getLogger(__name__)
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from .scraper import parse_forum
from .models import ParsedArticle

# Initialize LINE Bot API
configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

# Authorized user IDs (can use LINE commands)
AUTHORIZED_USER_IDS = [
    'U36595fa4ddd01f4f68d1833187ac9658',  # Tim
    'Ud675835f36eb4e002a24ad9558e62cbe',  # Tiffany
    'C1c6ca63a89d94ad16d3c366f03658c0b'   # 元老院
]

# Push notification targets (cron will send to these)
PUSH_TARGETS = [
    'U36595fa4ddd01f4f68d1833187ac9658',  # Tim
    'Ud675835f36eb4e002a24ad9558e62cbe',  # Tiffany
    'C0e7365c3db71bb31ebf8e5d0c2f94468',  # YoYo Club Group
    'C1c6ca63a89d94ad16d3c366f03658c0b'   # 元老院
]


def get_current_week_range():
    """
    Get current week range (Monday to Sunday).
    Returns (start_date, end_date)
    """
    today = date.today()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def is_authorized(event):
    """Check if user is authorized (only checks user_id, not group)."""
    user_id = getattr(event.source, 'user_id', None)
    return user_id and user_id in AUTHORIZED_USER_IDS


def health(request):
    """Health check endpoint for keep-alive pings."""
    return HttpResponse('OK')


@csrf_exempt
@require_POST
def callback(request):
    """LINE webhook callback endpoint."""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.body.decode('utf-8')

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return HttpResponseForbidden('Invalid signature')

    return HttpResponse('OK')


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """Handle text messages from LINE."""
    text = event.message.text.strip().lower()
    # Safely get user_id (works in both 1-on-1 and group chats)
    user_id = getattr(event.source, 'user_id', None)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # Command to show user ID and group ID (requires auth)
        if text == 'myid':
            if not is_authorized(event):
                return

            group_id = getattr(event.source, 'group_id', None)
            room_id = getattr(event.source, 'room_id', None)

            info_lines = []
            if user_id:
                info_lines.append(f"User ID: {user_id}")
            if group_id:
                info_lines.append(f"Group ID: {group_id}")
            if room_id:
                info_lines.append(f"Room ID: {room_id}")

            if info_lines:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="\n".join(info_lines))]
                    )
                )
            return

        # Command to show all articles in DB
        if text in ['db']:
            if not is_authorized(event):
                return

            articles = ParsedArticle.objects.all().order_by('-post_date')[:20]
            if articles:
                response_lines = [f"資料庫文章 (共 {ParsedArticle.objects.count()} 篇，顯示最新 20 篇):"]
                for article in articles:
                    response_lines.append(f"[{article.post_date}] {article.title}")
                response = "\n".join(response_lines)
            else:
                response = "資料庫沒有文章"

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )
            return

        # Command to get this week's articles
        if text in ['articles']:
            if not is_authorized(event):
                return

            # Parse forum for new articles first
            parse_forum()

            # Get current week range
            monday, sunday = get_current_week_range()

            # Get articles within this week
            week_articles = ParsedArticle.objects.filter(
                post_date__gte=monday,
                post_date__lte=sunday
            ).order_by('post_date')

            if week_articles:
                response_lines = [f"本週文章 ({monday.strftime('%m/%d')} - {sunday.strftime('%m/%d')}):"]
                for article in week_articles:
                    response_lines.append(f"[{article.title}]: {article.url}")
                response = "\n\n".join(response_lines)
            else:
                response = "本週沒有新文章"

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )


@csrf_exempt
@require_POST
def cron_scraper(request, secret):
    """Cron endpoint to scrape and push new articles to LINE."""
    logger.info("Cron job started")

    # Verify secret
    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        logger.warning("Cron job rejected: invalid secret")
        return HttpResponseForbidden('Invalid secret')

    # Get oldest article date in DB before scraping
    oldest_in_db = ParsedArticle.objects.order_by('post_date').first()
    oldest_date = oldest_in_db.post_date if oldest_in_db else None
    logger.info(f"DB oldest date: {oldest_date}, total articles: {ParsedArticle.objects.count()}")

    # Parse forum for new articles
    new_articles = parse_forum()
    logger.info(f"Scraped {len(new_articles)} new articles from forum")

    # Filter: only articles newer than latest in DB AND within this week
    monday, sunday = get_current_week_range()
    logger.info(f"This week range: {monday} to {sunday}")

    if oldest_date:
        # Only show articles newer than the oldest in DB
        new_this_week = [a for a in new_articles if a.post_date > oldest_date and monday <= a.post_date <= sunday]
    else:
        # DB was empty, show all this week's new articles
        new_this_week = [a for a in new_articles if monday <= a.post_date <= sunday]

    logger.info(f"New articles this week to push: {len(new_this_week)}")

    if new_this_week:
        # Build message (same format as articles command)
        response_lines = [f"本週新文章 ({monday.strftime('%m/%d')} - {sunday.strftime('%m/%d')}):"]
        for article in sorted(new_this_week, key=lambda x: x.post_date):
            response_lines.append(f"[{article.title}]: {article.url}")
        message = "\n\n".join(response_lines)

        # Push to all targets (users and groups)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            for target_id in PUSH_TARGETS:
                try:
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=target_id,
                            messages=[TextMessage(text=message)]
                        )
                    )
                    logger.info(f"Pushed to {target_id}")
                except Exception as e:
                    logger.error(f"Failed to push to {target_id}: {e}")

        logger.info(f"Cron job completed: {len(new_this_week)} articles pushed")
        return HttpResponse(f'OK: {len(new_this_week)} new articles pushed')

    logger.info("Cron job completed: no new articles this week")
    return HttpResponse('OK: No new articles this week')


@csrf_exempt
@require_POST
def clear_db(request, secret):
    """Clear all articles from DB."""
    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        return HttpResponseForbidden('Invalid secret')

    count, _ = ParsedArticle.objects.all().delete()
    return HttpResponse(f'OK: Deleted {count} articles')


@csrf_exempt
def debug_scraper(request, secret):
    """Debug endpoint to check forum scraping."""
    import requests
    from bs4 import BeautifulSoup
    from .scraper import parse_date_from_title, FORUM_URL

    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        return HttpResponseForbidden('Invalid secret')

    try:
        headers = {
            'User-Agent': 'YoYo-Bot/1.0',
            'X-Bot-Secret': 'yoyo2025scraper'
        }
        resp = requests.get(FORUM_URL, headers=headers, timeout=30)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.select('li.row')

        lines = [f'Forum URL: {FORUM_URL}', f'Status: {resp.status_code}', f'Rows found: {len(rows)}', '']
        for row in rows[:15]:
            title_link = row.select_one('a.topictitle')
            if title_link:
                title = title_link.get_text(strip=True)
                parsed = parse_date_from_title(title)
                lines.append(f'{parsed} | {title[:50]}')

        return HttpResponse('\n'.join(lines), content_type='text/plain')
    except Exception as e:
        return HttpResponse(f'Error: {e}', content_type='text/plain')
