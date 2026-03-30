import logging
from datetime import date, timedelta
from enum import Enum

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
    QuickReply,
    QuickReplyItem,
    MessageAction,
    CameraAction,
    CameraRollAction,
)
from linebot.v3.messaging.api import MessagingApiBlob
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent

from .scraper import parse_forum, extract_topic_from_title, get_weekday_name
from .models import ParsedArticle, AuthorizedUser, PushTarget
from .gist_storage import save_users_to_gist, save_targets_to_gist
from .dietary_storage import (
    add_food_entry, add_food_entries, remove_food_entry, remove_food_entries,
    get_food_entry_by_index, update_food_entry, get_today_log, get_history,
    get_all_users_today, get_tdee, get_streak,
)
from .ai_api import (
    estimate_nutrition, estimate_nutrition_from_image, parse_and_estimate_foods,
    modify_food_estimation, generate_diet_advice,
)
from .profile_storage import get_profile


# ── Command constants ──────────────────────────────────────────────────────────

class Cmd(str, Enum):
    """All bot command keywords as constants."""
    ADD = 'add'
    REMOVE = 'remove'
    MODIFY = 'modify'
    TODAY = 'today'
    HISTORY = 'history'
    REPORT = 'report'
    HELP = 'help'
    MYID = 'myid'
    DB = 'db'
    CLEAR = 'clear'
    ARTICLES = 'articles'
    GOAL = '會員目標'
    ADDUSER = 'adduser'
    REMOVEUSER = 'removeuser'
    LISTUSERS = 'listusers'
    ADDTARGET = 'addtarget'
    REMOVETARGET = 'removetarget'
    LISTTARGETS = 'listtargets'


# Chinese aliases → Cmd member
CHINESE_ALIASES = {
    '加': Cmd.ADD,
    '刪除': Cmd.REMOVE,
    '修改': Cmd.MODIFY,
    '今天': Cmd.TODAY,
    '報告': Cmd.REPORT,
    '歷史': Cmd.HISTORY,
}

# Derived from the enum — used to detect non-command text in pending states
_KNOWN_COMMANDS = tuple(cmd.value for cmd in Cmd)


# ── LINE Bot setup ─────────────────────────────────────────────────────────────

configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

# Track users waiting to input food text (user_id -> True)
_pending_add = {}

# Track users waiting to input remove indices (user_id -> True)
_pending_remove = {}


def _reply(api, token, text, **kwargs):
    """Send a text reply. Accepts optional quick_reply kwarg."""
    api.reply_message(
        ReplyMessageRequest(
            reply_token=token,
            messages=[TextMessage(text=text, **kwargs)],
        )
    )

def get_push_targets():
    """Get push notification targets from PushTarget table."""
    return list(PushTarget.objects.values_list('target_id', flat=True))


def format_weekly_message(articles, header="YOYO WEEKLY UPDATE"):
    """
    Format articles into the styled weekly update message.

    Example output:
        ••• YOYO WEEKLY UPDATE •••

        📅 Tuesday (3/17)
        📝 What will future archaeologists discover about us?
        👤 Host: Winston
        🔗 https://yoyo.club.tw/viewtopic.php?t=5462

        ────────────────────────────

        📅 Saturday (3/21)
        📝 Move It and Level Up Your Brain!
        👤 Host: Tim Lee
        🔗 https://yoyo.club.tw/viewtopic.php?t=5458
    """
    separator = "\n\n────────────────────────────\n\n"
    blocks = []

    for article in articles:
        topic = extract_topic_from_title(article.title)
        weekday = get_weekday_name(article.post_date)
        date_str = article.post_date.strftime('%-m/%-d')

        lines = [
            f"📅 {weekday} ({date_str})",
            f"📝 Topic: {topic}",
        ]
        if article.author:
            lines.append(f"👤 Host: {article.author}")
        lines.append(f"🔗 {article.url}")

        blocks.append("\n".join(lines))

    return f"••• {header} •••\n\n" + separator.join(blocks)


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

    lines = ["📋 Today's Food Log", "─" * 14]
    total_cal = total_p = total_c = total_f = 0

    for i, food in enumerate(foods, 1):
        cal = food.get('calories')
        p = food.get('protein')
        c = food.get('carbs')
        f = food.get('fat')

        desc = food.get('description', '')
        name_str = f"{food['name']} ({desc})" if desc else food['name']

        if cal is not None:
            lines.append(f"{i}. {name_str}")
            lines.append(f"    {cal:.0f} kcal | P {p:.1f}g | C {c:.1f}g | F {f:.1f}g")
            total_cal += cal
            total_p += p or 0
            total_c += c or 0
            total_f += f or 0
        else:
            lines.append(f"{i}. {name_str}")
            lines.append(f"    nutrition unavailable")

    lines.append("─" * 14)
    lines.append(f"🔥 {total_cal:.0f} kcal")
    lines.append(f"   P {total_p:.1f}g  |  C {total_c:.1f}g  |  F {total_f:.1f}g")
    return "\n".join(lines)


GOAL_DISPLAY = {'bulk': '增肌', 'maintain': '維持', 'cut': '減脂'}


def _get_goal_label(user_id):
    """Return Chinese goal label for a user, or empty string if not set."""
    profile = get_profile(user_id)
    if profile and profile.goal:
        return GOAL_DISPLAY.get(profile.goal, '')
    return ''


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

    # Chinese command aliases
    for zh, cmd in CHINESE_ALIASES.items():
        if text == zh or text.startswith(zh + ' '):
            raw_text = cmd.value + raw_text[len(zh):]
            text = raw_text.lower()
            break

    user_id = getattr(event.source, 'user_id', None)

    # Pending-state: if user previously tapped a Rich Menu button and this text
    # isn't a known command, prepend the appropriate command keyword.
    def _is_command(t):
        return any(t == c or t.startswith(c + ' ') for c in _KNOWN_COMMANDS)

    if user_id and _pending_add.pop(user_id, False):
        if not _is_command(text):
            raw_text = f'{Cmd.ADD.value} {raw_text}'
            text = raw_text.lower()

    if user_id and _pending_remove.pop(user_id, False):
        if text == '取消':
            with ApiClient(configuration) as api_client:
                _reply(MessagingApi(api_client), event.reply_token, "已取消")
            return
        if not _is_command(text):
            raw_text = f'{Cmd.REMOVE.value} {raw_text}'
            text = raw_text.lower()

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # Cancel command (from Quick Reply buttons)
        if text == '取消':
            _reply(line_bot_api, event.reply_token, "已取消")
            return

        # Placeholder button response
        if raw_text == '此功能即將推出':
            _reply(line_bot_api, event.reply_token, "此功能即將推出，敬請期待！")
            return

        # Help command (no auth required)
        if text == Cmd.HELP:
            help_lines = [
                "📋 指令列表：",
                "",
                "▸ help — 顯示此說明",
                "▸ myid — 顯示你的 User/Group/Room ID",
                "",
                "飲食追蹤（不需授權）：",
                "▸ add {描述} — 記錄食物（支援多項）",
                "▸ 直接傳食物照片 — AI 辨識並記錄",
                "▸ remove {編號} — 刪除（支援多筆，如 remove 1 3）",
                "▸ modify {編號} {修改內容} — AI 重新估算",
                "▸ today — 顯示今日飲食紀錄",
                "▸ history — 過去 7 天飲食摘要",
                "▸ report — 飲食報告 + AI 建議",
                "▸ report {問題} — 自訂飲食問題",
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
            _reply(line_bot_api, event.reply_token, "\n".join(help_lines))
            return

        if text == Cmd.MYID:
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
                _reply(line_bot_api, event.reply_token, "\n".join(info_lines))
            return

        # Command: add food (no auth required) — natural language, supports multiple items
        if text == Cmd.ADD or text.startswith(Cmd.ADD + ' '):
            food_text = raw_text[3:].strip() if len(raw_text) > 3 else ''
            if not food_text:
                _pending_add[user_id] = True
                _reply(
                    line_bot_api, event.reply_token,
                    "請輸入吃了什麼，或傳食物照片：\n例: 一碗滷肉飯和一杯豆漿",
                    quick_reply=QuickReply(items=[
                        QuickReplyItem(action=CameraAction(label="📷 拍照")),
                        QuickReplyItem(action=CameraRollAction(label="🖼 相簿")),
                    ]),
                )
                return
            else:
                foods_list = parse_and_estimate_foods(food_text)

                if not foods_list:
                    response = "Could not parse food items. Please try again."
                else:
                    saved = add_food_entries(user_id, foods_list)

                    if len(foods_list) == 1:
                        f = foods_list[0]
                        desc = f.get('description', '')
                        name_str = f"{f['name']} ({desc})" if desc else f['name']
                        response = (
                            f"Added: {name_str}\n"
                            f"{f['calories']:.0f} kcal, "
                            f"{f['protein']:.1f}g P, "
                            f"{f['carbs']:.1f}g C, "
                            f"{f['fat']:.1f}g F"
                        )
                        if f.get('basis'):
                            response += f"\n({f['basis']})"
                    else:
                        lines = [f"Added {len(foods_list)} items:"]
                        for i, f in enumerate(foods_list, 1):
                            desc = f.get('description', '')
                            name_str = f"{f['name']} ({desc})" if desc else f['name']
                            lines.append(
                                f"{i}. {name_str} — "
                                f"{f['calories']:.0f} kcal, "
                                f"{f['protein']:.1f}g P, "
                                f"{f['carbs']:.1f}g C, "
                                f"{f['fat']:.1f}g F"
                            )
                            if f.get('basis'):
                                lines.append(f"   ({f['basis']})")
                        response = "\n".join(lines)

                    if not saved:
                        response += "\n(Warning: failed to save to storage)"

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command: remove food by index (no auth required)
        # Supports: remove 1 | remove 1 3 5 | bare "remove" (shows today + waits)
        if text == Cmd.REMOVE or text.startswith(Cmd.REMOVE + ' '):
            args_text = raw_text[6:].strip() if len(raw_text) > 6 else ''

            # Bare "remove" — show today's log with Quick Reply buttons
            if not args_text:
                foods = get_today_log(user_id)
                if not foods:
                    _reply(line_bot_api, event.reply_token, "No food logged today.")
                    return

                report = build_daily_report(foods)

                # Quick Reply supports max 13 items; use 12 for food + 1 cancel
                if len(foods) <= 12:
                    qr_items = []
                    for i, food in enumerate(foods, 1):
                        label = f"{i}. {food['name']}"
                        if len(label) > 20:
                            label = label[:19] + "…"
                        qr_items.append(QuickReplyItem(
                            action=MessageAction(label=label, text=f"remove {i}")
                        ))
                    qr_items.append(QuickReplyItem(
                        action=MessageAction(label="取消", text="取消")
                    ))
                    _reply(
                        line_bot_api, event.reply_token,
                        f"{report}\n\n請點選要刪除的項目：",
                        quick_reply=QuickReply(items=qr_items),
                    )
                else:
                    # Fallback to text input for >12 entries
                    _pending_remove[user_id] = True
                    _reply(
                        line_bot_api, event.reply_token,
                        f"{report}\n\n請輸入要刪除的編號（可多筆，空格隔開）\n例: 1 3",
                    )
                return

            # Parse index numbers (support "1 3 5" or single "1")
            indices = []
            for part in args_text.split():
                if part.isdigit():
                    indices.append(int(part))

            if not indices:
                response = "Usage: remove {編號} [編號 ...]\n例: remove 1 或 remove 1 3 5"
            elif len(indices) == 1:
                removed = remove_food_entry(user_id, indices[0])
                if removed:
                    response = f"Removed: {removed['name']}"
                else:
                    response = f"Invalid index: {indices[0]}. Use 'today' to see the list."
            else:
                removed_list = remove_food_entries(user_id, indices)
                if removed_list:
                    names = ', '.join(r['name'] for r in removed_list)
                    response = f"Removed {len(removed_list)} items: {names}"
                else:
                    response = "No valid indices. Use 'today' to see the list."

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command: modify food by index (no auth required)
        if text.startswith(Cmd.MODIFY + ' '):
            parts = raw_text.split(maxsplit=2)
            if len(parts) < 3 or not parts[1].isdigit():
                response = "Usage: modify {編號} {修改內容}\nExample: modify 1 其實只有半碗"
            else:
                index = int(parts[1])
                modification = parts[2].strip()
                original = get_food_entry_by_index(user_id, index)
                if not original:
                    response = f"Invalid index: {index}. Use 'today' to see the list."
                else:
                    updated = modify_food_estimation(original, modification)
                    if not updated:
                        response = "AI failed to re-estimate. Please try again."
                    else:
                        saved = update_food_entry(user_id, index, updated)
                        desc = updated.get('description', '')
                        name_str = f"{updated['name']} ({desc})" if desc else updated['name']
                        response = (
                            f"Modified #{index}: {name_str}\n"
                            f"{updated['calories']:.0f} kcal, "
                            f"{updated['protein']:.1f}g P, "
                            f"{updated['carbs']:.1f}g C, "
                            f"{updated['fat']:.1f}g F"
                        )
                        if updated.get('basis'):
                            response += f"\n({updated['basis']})"
                        if not saved:
                            response += "\n(Warning: failed to save to storage)"

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command: today (no auth required)
        if text == Cmd.TODAY:
            foods = get_today_log(user_id)
            response = build_daily_report(foods)

            tdee = get_tdee(user_id)
            if tdee:
                total_cal = sum(f.get('calories', 0) or 0 for f in foods)
                remaining = tdee - total_cal
                goal_label = _get_goal_label(user_id)
                goal_str = f"  ({goal_label})" if goal_label else ""
                response += f"\n\n🎯 目標 {tdee} kcal{goal_str}  |  剩餘 {remaining:.0f} kcal"

            streak = get_streak(user_id)
            if streak > 0:
                response += f"\n🔥 連續 {streak} 天"

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command: history (no auth required)
        if text == Cmd.HISTORY:
            history = get_history(user_id)
            if not history:
                response = "No food logged in the past 7 days."
            else:
                lines = ["Past 7 days:"]
                for date_str, foods in history.items():
                    total_cal = sum(f.get('calories', 0) or 0 for f in foods)
                    count = len(foods)
                    # Format date as MM/DD
                    display_date = date_str[5:].replace('-', '/')
                    lines.append(f"{display_date} — {total_cal:.0f} kcal ({count} items)")
                response = "\n".join(lines)

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command: 會員目標 (handled via LIFF page, but catch text input)
        if raw_text == Cmd.GOAL:
            _reply(
                line_bot_api, event.reply_token,
                "請點選選單「更多功能」→「會員目標」來設定目標。",
            )
            return

        # Command: report [prompt] (no auth required) — daily report with AI advice
        if text == Cmd.REPORT or text.startswith(Cmd.REPORT + ' '):
            foods = get_today_log(user_id)
            report_lines = build_daily_report(foods)

            tdee = get_tdee(user_id)
            goal_label = _get_goal_label(user_id)
            if tdee:
                total_cal = sum(f.get('calories', 0) or 0 for f in foods)
                remaining = tdee - total_cal
                goal_str = f"  ({goal_label})" if goal_label else ""
                report_lines += f"\n\n🎯 目標 {tdee} kcal{goal_str}  |  剩餘 {remaining:.0f} kcal"

            # Get AI advice
            user_prompt = raw_text[7:].strip() if len(raw_text) > 7 else ''
            if foods:
                advice = generate_diet_advice(foods, tdee, user_prompt, goal_label)
                if advice:
                    report_lines += f"\n\n💡 AI Advice\n{'─' * 20}\n{advice}"

            _reply(line_bot_api, event.reply_token, report_lines)
            return

        # Command to show all articles in DB
        if text == Cmd.DB:
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

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command to clear all articles from DB
        if text == Cmd.CLEAR:
            if not is_authorized(event):
                return

            count, _ = ParsedArticle.objects.all().delete()
            _reply(line_bot_api, event.reply_token, f"已清除 {count} 篇文章")
            return

        # Command to get this week's articles
        if text == Cmd.ARTICLES:
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
                response = format_weekly_message(week_articles)
            else:
                response = "本週沒有新文章"

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command to add an authorized user
        if text.startswith(Cmd.ADDUSER):
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

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command to remove an authorized user
        if text.startswith(Cmd.REMOVEUSER):
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

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command to list all authorized users
        if text == Cmd.LISTUSERS:
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

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command to add a push target
        if text.startswith(Cmd.ADDTARGET):
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

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command to remove a push target
        if text.startswith(Cmd.REMOVETARGET):
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

            _reply(line_bot_api, event.reply_token, response)
            return

        # Command to list all push targets
        if text == Cmd.LISTTARGETS:
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

            _reply(line_bot_api, event.reply_token, response)
            return


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    """Handle image messages — identify food from photo and log nutrition."""
    user_id = getattr(event.source, 'user_id', None)
    message_id = event.message.id

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        blob_api = MessagingApiBlob(api_client)

        try:
            # Download image content
            image_response = blob_api.get_message_content(message_id)
            image_bytes = image_response
            mime_type = 'image/jpeg'

            # Estimate nutrition from image
            result = estimate_nutrition_from_image(image_bytes, mime_type)

            food_name = result.get('food_name')
            if not food_name:
                _reply(line_bot_api, event.reply_token,
                       "Could not identify food in this photo. Try a clearer photo or use 'add {food name}'.")
                return

            food_entry = {
                'name': food_name,
                'description': '',
                'calories': result['calories'],
                'protein': result['protein'],
                'carbs': result['carbs'],
                'fat': result['fat'],
                'basis': result.get('basis', ''),
            }

            saved = add_food_entry(user_id, food_entry)

            if result['calories'] is not None:
                response = (
                    f"Added: {food_name}\n"
                    f"{result['calories']:.0f} kcal, "
                    f"{result['protein']:.1f}g P, "
                    f"{result['carbs']:.1f}g C, "
                    f"{result['fat']:.1f}g F"
                )
                if result.get('basis'):
                    response += f"\n({result['basis']})"
            else:
                response = f"Added: {food_name} (nutrition estimation unavailable)"

            if not saved:
                response += "\n(Warning: failed to save to storage)"

            _reply(line_bot_api, event.reply_token, response)
        except Exception as e:
            logger.error(f"Image message handling error: {e}")
            _reply(line_bot_api, event.reply_token,
                   "Failed to process the image. Please try again.")


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
        sorted_articles = sorted(new_this_week, key=lambda x: x.post_date)
        message = format_weekly_message(sorted_articles)

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
            tdee = get_tdee(uid)
            if tdee:
                total_cal = sum(f.get('calories', 0) or 0 for f in foods)
                remaining = tdee - total_cal
                goal_label = _get_goal_label(uid)
                goal_str = f"  ({goal_label})" if goal_label else ""
                report += f"\n\n🎯 目標 {tdee} kcal{goal_str}  |  剩餘 {remaining:.0f} kcal"
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


@csrf_exempt
@require_POST
def dietary_reminder_cron(request, secret):
    """
    Cron endpoint to send reminders to users who haven't logged food in 7+ hours.
    Skips reminders during night hours (22:00 to 08:00 Taiwan time).
    """
    from datetime import datetime, timedelta, timezone as dt_timezone
    from .models import FoodEntry

    logger.info("=" * 50)
    logger.info("DIETARY REMINDER CRON STARTED")
    logger.info("=" * 50)

    expected_secret = getattr(settings, 'CRON_SECRET', '')
    if not expected_secret or secret != expected_secret:
        logger.warning("Dietary reminder cron rejected: invalid secret")
        return HttpResponseForbidden('Invalid secret')

    # Check current Taiwan time (UTC+8)
    TW_TZ = dt_timezone(timedelta(hours=8))
    now_tw = datetime.now(TW_TZ)
    current_hour = now_tw.hour
    logger.info(f"Current Taiwan time: {now_tw.strftime('%Y-%m-%d %H:%M:%S')}")

    # Skip during night hours (22:00 to 08:00)
    if current_hour >= 22 or current_hour < 8:
        logger.info(f"Skipping reminders during night hours (current hour: {current_hour})")
        logger.info("=" * 50)
        return HttpResponse(f'OK: Skipped night hours (hour: {current_hour})')

    # Get all push targets
    targets = list(PushTarget.objects.values_list('target_id', flat=True))
    logger.info(f"Total push targets: {len(targets)}")

    if not targets:
        logger.info("No push targets configured")
        logger.info("=" * 50)
        return HttpResponse('OK: No push targets')

    # Check each target for recent activity
    cutoff_time = now_tw - timedelta(hours=7)
    sent_count = 0

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        for target_id in targets:
            # Get the most recent food entry for this user
            latest_entry = FoodEntry.objects.filter(
                user_id=target_id
            ).order_by('-added_at').first()

            should_remind = False

            if not latest_entry:
                # No entries at all - send reminder
                should_remind = True
                logger.info(f"{target_id}: No entries found, sending reminder")
            else:
                # Convert latest entry time to Taiwan timezone
                latest_time = latest_entry.added_at.astimezone(TW_TZ)
                time_diff = now_tw - latest_time
                hours_since = time_diff.total_seconds() / 3600

                if hours_since > 7:
                    should_remind = True
                    logger.info(f"{target_id}: Last entry {hours_since:.1f}h ago, sending reminder")
                else:
                    logger.info(f"{target_id}: Last entry {hours_since:.1f}h ago, skip")

            if should_remind:
                reminder_msg = (
                    "嗨！記得記錄今天的飲食喔～\n\n"
                    "定期追蹤能幫助你更好地了解飲食習慣。\n"
                    "點選下方選單「新增食物」或直接傳送食物照片給我吧！"
                )

                try:
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=target_id,
                            messages=[TextMessage(text=reminder_msg)]
                        )
                    )
                    sent_count += 1
                    logger.info(f"Sent reminder to {target_id}")
                except Exception as e:
                    logger.error(f"Failed to send reminder to {target_id}: {e}")

    logger.info(f"Dietary reminder cron completed: {sent_count} reminders sent")
    logger.info("=" * 50)
    return HttpResponse(f'OK: {sent_count} reminders sent')
