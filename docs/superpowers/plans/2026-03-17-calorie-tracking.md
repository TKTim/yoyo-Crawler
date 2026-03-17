# Calorie Intake Tracking Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add calorie intake tracking to the LINE bot — users log food via `add` command, nutrition is estimated via Gemini API, and a daily report is pushed at 22:00 Taiwan time.

**Architecture:** Two new modules (`dietary_storage.py` for Gist-based CRUD, `gemini_api.py` for Gemini API calls) plus new command handlers in `views.py`, a new cron endpoint, and a GitHub Actions workflow.

**Tech Stack:** Django 5.1.4, line-bot-sdk 3.21.0, Google Gemini API (free tier, `gemini-2.0-flash`), GitHub Gist API, `requests` library.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `mylinebot_code/dietary_storage.py` | Gist-based CRUD for dietary logs (load, save, add entry, query, prune) |
| Create | `mylinebot_code/gemini_api.py` | Google Gemini API client for nutrition estimation |
| Modify | `mylinebot_code/views.py` | Add `add`, `today`, `report` command handlers + `dietary_report_cron` endpoint |
| Modify | `mylinebot_code/apps.py` | Load dietary logs from Gist on startup |
| Modify | `mylinebot_config/urls.py` | Add `dietary-report/<secret>/` route |
| Modify | `.env.example` | Add `GEMINI_API_KEY` |
| Create | `.github/workflows/daily-dietary-report.yml` | 22:00 Taiwan time cron to trigger dietary report endpoint |

---

### Task 1: Dietary Storage Module

**Files:**
- Create: `mylinebot_code/dietary_storage.py`

This module manages the in-memory dietary log dict and syncs it to/from the Gist file `yoyo_dietary_logs.json`. It follows the same pattern as `gist_storage.py`.

- [ ] **Step 1: Create `dietary_storage.py` with in-memory store and Gist load/save**

```python
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
    """Remove entries older than 30 days for all users."""
    cutoff = (datetime.now(TW_TZ) - timedelta(days=30)).strftime('%Y-%m-%d')
    for user_id in list(_dietary_logs.keys()):
        dates = _dietary_logs[user_id]
        old_dates = [d for d in dates if d < cutoff]
        for d in old_dates:
            del dates[d]
        # Remove user entirely if no dates left
        if not dates:
            del _dietary_logs[user_id]
```

- [ ] **Step 2: Verify file was created correctly**

Run: `python -c "import ast; ast.parse(open('mylinebot_code/dietary_storage.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add mylinebot_code/dietary_storage.py
git commit -m "feat: add dietary storage module for Gist-based food logging"
```

---

### Task 2: Gemini API Client

**Files:**
- Create: `mylinebot_code/gemini_api.py`

- [ ] **Step 1: Create `gemini_api.py`**

```python
"""
Google Gemini API client for nutrition estimation.
Uses gemini-2.0-flash (free tier: 15 RPM, 1M tokens/day).
"""
import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = 'gemini-2.0-flash'
GEMINI_URL = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'


def estimate_nutrition(food_name, description=''):
    """
    Call Gemini API to estimate nutrition for a food item.
    Returns dict with keys: calories, protein, carbs, fat.
    Values are floats or None if estimation fails.
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set, cannot estimate nutrition")
        return {'calories': None, 'protein': None, 'carbs': None, 'fat': None}

    food_desc = food_name
    if description:
        food_desc = f"{food_name}, {description}"

    prompt = (
        f"Estimate the nutritional content of this food: \"{food_desc}\".\n"
        "Return ONLY a JSON object with these numeric fields (no markdown, no explanation):\n"
        '{"calories": <number>, "protein": <number>, "carbs": <number>, "fat": <number>}\n'
        "Values should be in kcal for calories and grams for protein/carbs/fat.\n"
        "If you cannot estimate, use 0 for all values."
    )

    try:
        response = requests.post(
            GEMINI_URL,
            params={'key': GEMINI_API_KEY},
            json={
                'contents': [{'parts': [{'text': prompt}]}]
            },
            timeout=15
        )
        response.raise_for_status()

        data = response.json()
        text = data['candidates'][0]['content']['parts'][0]['text']

        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()
        if text.startswith('json'):
            text = text[4:].strip()

        result = json.loads(text)
        return {
            'calories': float(result.get('calories', 0)),
            'protein': float(result.get('protein', 0)),
            'carbs': float(result.get('carbs', 0)),
            'fat': float(result.get('fat', 0)),
        }
    except Exception as e:
        logger.error(f"Gemini API error for '{food_desc}': {e}")
        return {'calories': None, 'protein': None, 'carbs': None, 'fat': None}
```

- [ ] **Step 2: Verify file syntax**

Run: `python -c "import ast; ast.parse(open('mylinebot_code/gemini_api.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add mylinebot_code/gemini_api.py
git commit -m "feat: add Gemini API client for nutrition estimation"
```

---

### Task 3: LINE Bot Commands (`add`, `today`, `report`)

**Files:**
- Modify: `mylinebot_code/views.py:74-360` (inside `handle_text_message`)

Add three new command handlers inside the existing `handle_text_message` function, **before** the existing authorized-only commands (after the `myid` block, around line 133). These commands don't require authorization.

- [ ] **Step 1: Add imports at top of `views.py`**

Add after the existing `from .gist_storage import ...` line (line 25):

```python
from .dietary_storage import add_food_entry, get_today_log, get_all_users_today, save_dietary_logs
from .gemini_api import estimate_nutrition
```

- [ ] **Step 2: Add helper function `build_daily_report` before `handle_text_message`**

Add after the `is_authorized` function (after line 51):

```python
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
```

- [ ] **Step 3: Add `add` command handler in `handle_text_message`**

Insert after the `myid` command block (after line 133, before the `db` command), inside the `with ApiClient(configuration) as api_client:` block:

```python
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
```

- [ ] **Step 4: Add `today` command handler**

Insert right after the `add` command block:

```python
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
```

- [ ] **Step 5: Add `report` command handler**

Insert right after the `today` command block:

```python
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
```

- [ ] **Step 6: Update help text to include new commands**

In the `help` command block (lines 87-103), add these lines to the help text list, before the `"以下指令需要授權："` line:

```python
                "",
                "飲食追蹤（不需授權）：",
                "▸ add {食物} {描述} — 記錄食物攝取",
                "▸ today — 顯示今日飲食紀錄",
                "▸ report — 產生今日飲食報告",
```

- [ ] **Step 7: Verify syntax**

Run: `python -c "import ast; ast.parse(open('mylinebot_code/views.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add mylinebot_code/views.py
git commit -m "feat: add LINE bot commands for calorie tracking (add, today, report)"
```

---

### Task 4: Daily Report Cron Endpoint

**Files:**
- Modify: `mylinebot_code/views.py` (add new view function at end)
- Modify: `mylinebot_config/urls.py`

- [ ] **Step 1: Add `dietary_report_cron` endpoint to `views.py`**

Append at the end of `views.py`:

```python
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
```

- [ ] **Step 2: Add URL route in `urls.py`**

Add this line to `urlpatterns` in `mylinebot_config/urls.py`, after the `targets` path:

```python
    path('dietary-report/<str:secret>/', views.dietary_report_cron, name='dietary_report_cron'),
```

- [ ] **Step 3: Verify syntax of both files**

Run: `python -c "import ast; ast.parse(open('mylinebot_code/views.py').read()); print('views OK')" && python -c "import ast; ast.parse(open('mylinebot_config/urls.py').read()); print('urls OK')"`
Expected: `views OK` then `urls OK`

- [ ] **Step 4: Commit**

```bash
git add mylinebot_code/views.py mylinebot_config/urls.py
git commit -m "feat: add daily dietary report cron endpoint"
```

---

### Task 5: Startup Loading + Config

**Files:**
- Modify: `mylinebot_code/apps.py`
- Modify: `.env.example`

- [ ] **Step 1: Update `apps.py` to load dietary logs on startup**

In the `ready()` method, add `load_dietary_logs` to the import and call it:

Change the try block (lines 21-25) to:

```python
        try:
            from .gist_storage import load_articles_from_gist, load_users_from_gist, load_targets_from_gist
            from .dietary_storage import load_dietary_logs
            load_articles_from_gist()
            load_users_from_gist()
            load_targets_from_gist()
            load_dietary_logs()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to load from Gist on startup: {e}")
```

- [ ] **Step 2: Add `GEMINI_API_KEY` to `.env.example`**

Append to `.env.example`:

```
GEMINI_API_KEY=
```

- [ ] **Step 3: Commit**

```bash
git add mylinebot_code/apps.py .env.example
git commit -m "feat: load dietary logs on startup, add GEMINI_API_KEY to env example"
```

---

### Task 6: GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/daily-dietary-report.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
name: Daily Dietary Report

on:
  schedule:
    # Run at 14:00 UTC every day (22:00 Taiwan time)
    - cron: '0 14 * * *'
  workflow_dispatch:  # Allow manual trigger

jobs:
  trigger-report:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger dietary report endpoint
        run: |
          curl -X POST "${{ secrets.RENDER_URL }}/dietary-report/${{ secrets.CRON_SECRET }}/" \
            -H "Content-Type: application/json" \
            --fail --silent --show-error
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/daily-dietary-report.yml
git commit -m "feat: add daily dietary report GitHub Actions workflow (22:00 Taiwan)"
```

---

### Task 7: Manual Smoke Test

- [ ] **Step 1: Run Django check**

Run: `cd /Users/tim_lee/Code/yoyo-English && python manage.py check`
Expected: `System check identified no issues.`

- [ ] **Step 2: Verify all imports resolve**

Run: `cd /Users/tim_lee/Code/yoyo-English && python -c "from mylinebot_code.dietary_storage import add_food_entry, get_today_log, get_all_users_today; from mylinebot_code.gemini_api import estimate_nutrition; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 3: Final commit if any fixes were needed, then done**
