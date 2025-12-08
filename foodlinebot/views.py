from datetime import date, timedelta

from django.conf import settings
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

# Authorized user IDs
AUTHORIZED_USER_IDS = [
    'U36595fa4ddd01f4f68d1833187ac9658',  # Tim
    'Ud675835f36eb4e002a24ad9558e62cbe' # Tiffany
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

        # Command to show user ID (for adding to authorized list)
        if text == 'myid':
            if user_id:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"Your ID: {user_id}")]
                    )
                )
            return

        # Command to show all articles in DB
        if text in ['db']:
            # Check if user is authorized - no reply if not
            if not user_id or user_id not in AUTHORIZED_USER_IDS:
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
            # Check if user is authorized - no reply if not
            if not user_id or user_id not in AUTHORIZED_USER_IDS:
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
    # Verify secret
    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        return HttpResponseForbidden('Invalid secret')

    # Parse forum for new articles
    new_articles = parse_forum()

    if new_articles:
        # Build message
        response_lines = [f"發現 {len(new_articles)} 篇新文章:"]
        for article in new_articles:
            response_lines.append(f"[{article.post_date}] {article.title}")
            response_lines.append(f"{article.url}")
        message = "\n".join(response_lines)

        # Push to all authorized users
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            for user_id in AUTHORIZED_USER_IDS:
                try:
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=user_id,
                            messages=[TextMessage(text=message)]
                        )
                    )
                except Exception:
                    pass  # Skip if user blocked bot

        return HttpResponse(f'OK: {len(new_articles)} new articles pushed')

    return HttpResponse('OK: No new articles')


@csrf_exempt
@require_POST
def clear_db(request, secret):
    """Clear all articles from DB."""
    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        return HttpResponseForbidden('Invalid secret')

    count, _ = ParsedArticle.objects.all().delete()
    return HttpResponse(f'OK: Deleted {count} articles')
