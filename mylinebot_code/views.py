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
from .models import ParsedArticle, AuthorizedUser, PushTarget
from .gist_storage import save_users_to_gist, save_targets_to_gist
from .dietary_storage import add_food_entry, get_today_log, get_all_users_today
from .gemini_api import estimate_nutrition

# Initialize LINE Bot API
configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

def get_push_targets():
    """Get push notification targets from PushTarget table."""
    return list(PushTarget.objects.values_list('target_id', flat=True))


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
    """Check if user is authorized via DB lookup."""
    user_id = getattr(event.source, 'user_id', None)
    return user_id and AuthorizedUser.objects.filter(user_id=user_id).exists()


def build_daily_report(foods):
    """Build a daily food report message from a list of food entries."""
    if not foods:
        return "No food logged today."

    lines = ["Today's food log:"]
    total_cal = total_p = total_c = total_f = 0

    for i, food in enumerate(foods, 1):
        cal = food.get('calories')
        p = food.get('protein')
        c = food.get('carbs')
        f = food.get('fat')

        if cal is not None:
            lines.append(f"{i}. {food['name']} — {cal:.0f} kcal, {p:.1f}g P, {c:.1f}g C, {f:.1f}g F")
            total_cal += cal
            total_p += p or 0
            total_c += c or 0
            total_f += f or 0
        else:
            lines.append(f"{i}. {food['name']} — nutrition unavailable")

    lines.append(f"\nTotal: {total_cal:.0f} kcal, {total_p:.1f}g protein, {total_c:.1f}g carbs, {total_f:.1f}g fat")
    return "\n".join(lines)


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
    raw_text = event.message.text.strip()
    text = raw_text.lower()
    # Safely get user_id (works in both 1-on-1 and group chats)
    user_id = getattr(event.source, 'user_id', None)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # Help command (no auth required)
        if text == 'help':
            help_lines = [
                "📋 指令列表：",
                "",
                "▸ help — 顯示此說明",
                "▸ myid — 顯示你的 User/Group/Room ID",
                "",
                "飲食追蹤（不需授權）：",
                "▸ add {食物} {描述} — 記錄食物攝取",
                "▸ today — 顯示今日飲食紀錄",
                "▸ report — 產生今日飲食報告",
                "",
                "以下指令需要授權：",
                "▸ articles — 取得本週文章",
                "▸ db — 顯示資料庫文章列表",
                "▸ clear — 清除資料庫所有文章",
                "▸ adduser <id> <名稱> — 新增授權用戶",
                "▸ removeuser <id> — 移除授權用戶",
                "▸ listusers — 列出所有授權用戶",
                "▸ addtarget <id> <名稱> — 新增推播對象",
                "▸ removetarget <id> — 移除推播對象",
                "▸ listtargets — 列出所有推播對象",
            ]
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="\n".join(help_lines))]
                )
            )
            return

        # Command to show user ID and group ID (requires auth)
        if text == 'myid':

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

        # Command: add food (no auth required)
        if text.startswith('add '):
            parts = raw_text.split(maxsplit=2)
            if len(parts) < 2:
                response = "Usage: add {food_name} {description}"
            else:
                food_name = parts[1]
                description = parts[2] if len(parts) > 2 else ''

                nutrition = estimate_nutrition(food_name, description)

                food_entry = {
                    'name': food_name,
                    'description': description,
                    **nutrition,
                }

                saved = add_food_entry(user_id, food_entry)

                if nutrition['calories'] is not None:
                    response = (
                        f"Added: {food_name} "
                        f"({nutrition['calories']:.0f} kcal, "
                        f"{nutrition['protein']:.1f}g protein, "
                        f"{nutrition['carbs']:.1f}g carbs, "
                        f"{nutrition['fat']:.1f}g fat)"
                    )
                else:
                    response = f"Added: {food_name} (nutrition estimation unavailable)"

                if not saved:
                    response += "\n(Warning: failed to save to storage)"

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )
            return

        # Command: today (no auth required)
        if text == 'today':
            foods = get_today_log(user_id)
            response = build_daily_report(foods)

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )
            return

        # Command: report (no auth required) — same as daily auto-report
        if text == 'report':
            foods = get_today_log(user_id)
            response = build_daily_report(foods)

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
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

        # Command to clear all articles from DB
        if text == 'clear':
            if not is_authorized(event):
                return

            count, _ = ParsedArticle.objects.all().delete()
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=f"已清除 {count} 篇文章")]
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
            return

        # Command to add an authorized user
        if text.startswith('adduser'):
            if not is_authorized(event):
                return

            parts = raw_text.split(maxsplit=2)
            if len(parts) < 2:
                response = "用法: adduser <id> [名稱]"
            else:
                new_id = parts[1]
                label = parts[2] if len(parts) > 2 else ''
                _, created = AuthorizedUser.objects.get_or_create(
                    user_id=new_id,
                    defaults={'label': label}
                )
                if created:
                    save_users_to_gist()
                    response = f"已新增授權用戶: {label or new_id}"
                else:
                    response = f"用戶已存在: {new_id}"

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )
            return

        # Command to remove an authorized user
        if text.startswith('removeuser'):
            if not is_authorized(event):
                return

            parts = raw_text.split(maxsplit=1)
            if len(parts) < 2:
                response = "用法: removeuser <id>"
            else:
                remove_id = parts[1]
                deleted, _ = AuthorizedUser.objects.filter(user_id=remove_id).delete()
                if deleted:
                    save_users_to_gist()
                    response = f"已移除授權用戶: {remove_id}"
                else:
                    response = f"找不到用戶: {remove_id}"

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )
            return

        # Command to list all authorized users
        if text == 'listusers':
            if not is_authorized(event):
                return

            users = AuthorizedUser.objects.all().order_by('created_at')
            if users:
                response_lines = [f"授權用戶 (共 {users.count()} 位):"]
                for u in users:
                    if u.label:
                        response_lines.append(f"▸ {u.label} ({u.user_id})")
                    else:
                        response_lines.append(f"▸ {u.user_id}")
                response = "\n".join(response_lines)
            else:
                response = "沒有授權用戶"

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )
            return

        # Command to add a push target
        if text.startswith('addtarget'):
            if not is_authorized(event):
                return

            parts = raw_text.split(maxsplit=2)
            if len(parts) < 2:
                response = "用法: addtarget <id> [名稱]"
            else:
                new_id = parts[1]
                label = parts[2] if len(parts) > 2 else ''
                _, created = PushTarget.objects.get_or_create(
                    target_id=new_id,
                    defaults={'label': label}
                )
                if created:
                    save_targets_to_gist()
                    response = f"已新增推播對象: {label or new_id}"
                else:
                    response = f"推播對象已存在: {new_id}"

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )
            return

        # Command to remove a push target
        if text.startswith('removetarget'):
            if not is_authorized(event):
                return

            parts = raw_text.split(maxsplit=1)
            if len(parts) < 2:
                response = "用法: removetarget <id>"
            else:
                remove_id = parts[1]
                deleted, _ = PushTarget.objects.filter(target_id=remove_id).delete()
                if deleted:
                    save_targets_to_gist()
                    response = f"已移除推播對象: {remove_id}"
                else:
                    response = f"找不到推播對象: {remove_id}"

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )
            return

        # Command to list all push targets
        if text == 'listtargets':
            if not is_authorized(event):
                return

            targets = PushTarget.objects.all().order_by('created_at')
            if targets:
                response_lines = [f"推播對象 (共 {targets.count()} 位):"]
                for t in targets:
                    if t.label:
                        response_lines.append(f"▸ {t.label} ({t.target_id})")
                    else:
                        response_lines.append(f"▸ {t.target_id}")
                response = "\n".join(response_lines)
            else:
                response = "沒有推播對象"

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response)]
                )
            )
            return


@csrf_exempt
@require_POST
def cron_scraper(request, secret):
    """Cron endpoint to scrape and push new articles to LINE."""
    logger.info("=" * 50)
    logger.info("CRON JOB STARTED")
    logger.info("=" * 50)

    # Verify secret
    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        logger.warning("Cron job rejected: invalid secret")
        return HttpResponseForbidden('Invalid secret')

    # Get current week range
    monday, sunday = get_current_week_range()
    logger.info(f"Today: {date.today()} | Week range: {monday} to {sunday}")

    # Parse forum for new articles (only returns articles not already in DB, and saves them)
    new_articles = parse_forum()
    logger.info(f"Scraped {len(new_articles)} new articles from forum")

    # Log details of new articles
    for article in new_articles:
        logger.info(f"  NEW: {article.post_date} | {article.title[:40]} | {article.url}")

    # Filter new articles to only those within this week
    new_this_week = [a for a in new_articles if monday <= a.post_date <= sunday]

    logger.info(f"New articles this week to push: {len(new_this_week)}")
    for article in new_this_week:
        logger.info(f"  PUSH: {article.post_date} | {article.title[:40]}")

    if new_this_week:
        # Build message (same format as articles command)
        response_lines = [f"本週新文章 ({monday.strftime('%m/%d')} - {sunday.strftime('%m/%d')}):"]
        for article in sorted(new_this_week, key=lambda x: x.post_date):
            response_lines.append(f"[{article.title}]: {article.url}")
        message = "\n\n".join(response_lines)

        # Push to all targets (users and groups)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            for target_id in get_push_targets():
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
        logger.info("=" * 50)
        return HttpResponse(f'OK: {len(new_this_week)} new articles pushed')

    logger.info("Cron job completed: no new articles this week")
    logger.info("=" * 50)
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
def api_users(request, secret):
    """API endpoint to list/add/remove authorized users."""
    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        return HttpResponseForbidden('Invalid secret')

    # POST: add or remove a user
    if request.method == 'POST':
        action = request.POST.get('action', '')
        user_id = request.POST.get('user_id', '')
        label = request.POST.get('label', '')

        if action == 'add' and user_id:
            _, created = AuthorizedUser.objects.get_or_create(
                user_id=user_id, defaults={'label': label}
            )
            save_users_to_gist()
            status = 'created' if created else 'already exists'
            return HttpResponse(f'{status}: {user_id}', content_type='text/plain')

        if action == 'remove' and user_id:
            deleted, _ = AuthorizedUser.objects.filter(user_id=user_id).delete()
            save_users_to_gist()
            status = 'removed' if deleted else 'not found'
            return HttpResponse(f'{status}: {user_id}', content_type='text/plain')

        return HttpResponse('Bad request: need action (add/remove) and user_id', status=400)

    # GET: list all users
    users = AuthorizedUser.objects.all().order_by('created_at')
    lines = [f'Authorized users ({users.count()}):']
    for u in users:
        lines.append(f'  {u.user_id}  {u.label}')
    return HttpResponse('\n'.join(lines), content_type='text/plain')


@csrf_exempt
def api_targets(request, secret):
    """API endpoint to list/add/remove push targets."""
    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        return HttpResponseForbidden('Invalid secret')

    if request.method == 'POST':
        action = request.POST.get('action', '')
        target_id = request.POST.get('target_id', '')
        label = request.POST.get('label', '')

        if action == 'add' and target_id:
            _, created = PushTarget.objects.get_or_create(
                target_id=target_id, defaults={'label': label}
            )
            save_targets_to_gist()
            status = 'created' if created else 'already exists'
            return HttpResponse(f'{status}: {target_id}', content_type='text/plain')

        if action == 'remove' and target_id:
            deleted, _ = PushTarget.objects.filter(target_id=target_id).delete()
            save_targets_to_gist()
            status = 'removed' if deleted else 'not found'
            return HttpResponse(f'{status}: {target_id}', content_type='text/plain')

        return HttpResponse('Bad request: need action (add/remove) and target_id', status=400)

    targets = PushTarget.objects.all().order_by('created_at')
    lines = [f'Push targets ({targets.count()}):']
    for t in targets:
        lines.append(f'  {t.target_id}  {t.label}')
    return HttpResponse('\n'.join(lines), content_type='text/plain')


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
            'X-Bot-Secret': 'yoyo2025scraper',
        }
        resp = requests.get(FORUM_URL, headers=headers, timeout=30)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.select('li.row')

        lines = [f'Forum URL: {FORUM_URL}', f'Status: {resp.status_code}', f'Rows found: {len(rows)}',
                 f'Response headers: {dict(resp.headers)}',
                 f'Body (first 500 chars): {resp.text[:500]}', '']
        for row in rows[:15]:
            title_link = row.select_one('a.topictitle')
            if title_link:
                title = title_link.get_text(strip=True)
                parsed = parse_date_from_title(title)
                lines.append(f'{parsed} | {title[:50]}')

        return HttpResponse('\n'.join(lines), content_type='text/plain')
    except Exception as e:
        return HttpResponse(f'Error: {e}', content_type='text/plain')


@csrf_exempt
@require_POST
def dietary_report_cron(request, secret):
    """Cron endpoint to send daily dietary reports to all users with entries today."""
    logger.info("=" * 50)
    logger.info("DIETARY REPORT CRON STARTED")
    logger.info("=" * 50)

    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        logger.warning("Dietary report cron rejected: invalid secret")
        return HttpResponseForbidden('Invalid secret')

    users_today = get_all_users_today()
    logger.info(f"Users with entries today: {len(users_today)}")

    if not users_today:
        logger.info("No dietary entries today, nothing to report")
        return HttpResponse('OK: No entries today')

    sent_count = 0
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        for uid, foods in users_today.items():
            report = build_daily_report(foods)
            try:
                line_bot_api.push_message(
                    PushMessageRequest(
                        to=uid,
                        messages=[TextMessage(text=f"Daily Diet Report:\n\n{report}")]
                    )
                )
                sent_count += 1
                logger.info(f"Sent dietary report to {uid}")
            except Exception as e:
                logger.error(f"Failed to send dietary report to {uid}: {e}")

    logger.info(f"Dietary report cron completed: {sent_count} reports sent")
    logger.info("=" * 50)
    return HttpResponse(f'OK: {sent_count} reports sent')
