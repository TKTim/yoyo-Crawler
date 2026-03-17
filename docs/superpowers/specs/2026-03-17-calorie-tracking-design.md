# Calorie Intake Tracking — Design Spec

## Overview

Add calorie intake tracking to the yoyo-English LINE bot. Users log food via LINE commands, nutrition is estimated via Google Gemini API, and a daily report is pushed at 22:00 Taiwan time.

## Data Model

Single Gist file: `yoyo_dietary_logs.json`

```json
{
  "<line_user_id>": {
    "2026-03-17": {
      "foods": [
        {
          "name": "apple",
          "description": "medium, raw",
          "calories": 95,
          "protein": 0.5,
          "carbs": 25.0,
          "fat": 0.3,
          "added_at": "2026-03-17T08:30:00"
        }
      ]
    }
  }
}
```

- Keyed by LINE `user_id` → ISO date string → `foods[]`
- No Django model — pure Gist JSON storage (consistent with existing gist_storage.py pattern)
- Data retention: 30 days. Entries older than 30 days are pruned on each save operation.

## New Files

### `mylinebot_code/dietary_storage.py`

Gist-based CRUD for dietary logs. Mirrors the pattern in `gist_storage.py`.

**Functions:**
- `load_dietary_logs()` — Load from Gist into in-memory dict
- `save_dietary_logs()` — Write in-memory dict back to Gist
- `add_food_entry(user_id, food_entry)` — Append a food to today's log for a user
- `get_today_log(user_id)` — Return today's food list for a user
- `get_all_users_today()` — Return dict of all users who have entries today
- `prune_old_entries()` — Remove entries older than 30 days

**Gist file name:** `yoyo_dietary_logs.json`

Uses the same `GITHUB_GIST_TOKEN` and `GIST_ID` env vars as existing storage.

### `mylinebot_code/gemini_api.py`

Google Gemini API client for nutrition estimation.

**Functions:**
- `estimate_nutrition(food_name, description)` — Call Gemini API, return dict with `calories`, `protein`, `carbs`, `fat`

**Details:**
- Model: `gemini-2.0-flash` (free tier: 15 RPM, 1M tokens/day)
- API endpoint: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent`
- Auth: API key via `GEMINI_API_KEY` env var
- Prompt requests JSON-only response with numeric values
- On failure (timeout, API error, parse error): return `None` values for all nutrition fields
- No third-party SDK needed — plain `requests.post()`

## LINE Bot Commands

All commands are open to any user (no authorization required). Data is isolated per user_id.

### `add {food_name} {description}`

1. Parse: first word after "add" = food name, rest = description
2. Call `estimate_nutrition(food_name, description)`
3. Build food entry dict with name, description, nutrition values, timestamp
4. Call `add_food_entry(user_id, food_entry)`
5. Reply with summary: `"Added: apple (95 kcal, 0.5g protein, 25.0g carbs, 0.3g fat)"`
6. If Gemini fails: save with null nutrition, reply `"Added: apple (nutrition estimation unavailable)"`

### `today`

1. Call `get_today_log(user_id)`
2. If empty: reply `"No food logged today."`
3. If entries exist: list each food with nutrition, then show totals

Reply format:
```
Today's food log:
1. apple — 95 kcal, 0.5g P, 25.0g C, 0.3g F
2. chicken lunch box — 650 kcal, 35g P, 80g C, 20g F

Total: 745 kcal, 35.5g protein, 105g carbs, 20.3g fat
```

### `report`

Same output as the automated 22:00 daily report, triggered manually.

## Daily Report (22:00 Taiwan Time)

### GitHub Actions Workflow

File: `.github/workflows/daily-dietary-report.yml`
- Schedule: `0 14 * * *` (14:00 UTC = 22:00 CST)
- Action: `POST /dietary-report/<secret>/`
- Uses same `CRON_SECRET` as existing cron job

### Endpoint

`POST /dietary-report/<secret>/`

Handler: `dietary_report_cron()` in `views.py`

1. Verify secret matches `CRON_SECRET`
2. Call `get_all_users_today()` to get all users with entries today
3. For each user:
   a. Build report message (same format as `report` command)
   b. Push via LINE `MessagingApi.push_message()` to that user_id
4. Return JSON response with count of reports sent

## URL Configuration

Add to `mylinebot_config/urls.py`:
```python
path('dietary-report/<str:secret>/', views.dietary_report_cron, name='dietary_report_cron'),
```

## Environment Variables

New variable to add:
- `GEMINI_API_KEY` — Google Gemini API key

Add to `.env.example` for documentation.

## Startup Loading

Update `apps.py` `ready()` to also load dietary logs from Gist on startup (same pattern as existing article/user/target loading).

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Gemini API timeout/error | Save food with null nutrition, inform user |
| Empty food name (`add` with no args) | Reply with usage: `"Usage: add {food} {description}"` |
| No entries for today (`today`/`report`) | Reply `"No food logged today."` |
| Gist save failure | Log error, reply to user that save failed |
| Daily report — user has no entries | Skip that user (no message sent) |

## Dependencies

No new pip packages required. Uses `requests` (already installed) for both Gemini API and Gist API calls.
