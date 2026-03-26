# YoYo English — LINE Bot

Django-based LINE messaging bot with two features: English article curation from a forum, and AI-powered dietary tracking with nutrition estimation.

## Tech Stack

- **Backend**: Django 5.1.4, Python 3.10, SQLite
- **Deployment**: AWS Lightsail, Gunicorn + Nginx, systemd (`yoyo-linebot` service)
- **LINE SDK**: line-bot-sdk 3.21.0 (v3 messaging API)
- **AI**: Google Gemini API (REST, no SDK) with multi-model fallback
- **Storage**: SQLite primary + GitHub Gist write-through backup (for ephemeral FS recovery)
- **Static files**: WhiteNoise

## Project Layout

```
mylinebot_config/          # Django project config
  settings.py              # Settings — reads env vars, WhiteNoise, SQLite
  urls.py                  # All URL routes (no app-level urls.py)

mylinebot_code/            # Main Django app
  views.py                 # LINE webhook handler + all bot command logic
  models.py                # ParsedArticle, AuthorizedUser, PushTarget, FoodEntry, UserTdee
  dietary_storage.py       # CRUD for food entries (DB + Gist sync)
  gemini_api.py            # Gemini API: nutrition estimation, food parsing, diet advice
  gist_storage.py          # GitHub Gist backup: save/load articles, users, targets, dietary
  scraper.py               # Forum scraper for yoyo.club.tw articles
  liff_views.py            # LIFF web editor page + REST API
  apps.py                  # AppConfig.ready() loads data from Gist on startup
  templates/
    liff_editor.html       # LIFF frontend (vanilla JS, single-file)
  management/commands/
    setup_richmenu.py      # Create LINE Rich Menu with Pillow-generated image
    parse_forum.py         # Manual forum scrape
    setup_gist.py          # Create initial Gist

deploy.sh                  # Git pull → pip install → migrate → collectstatic → restart
```

## Models

**FoodEntry** — one row per food item:
- `user_id` (CharField, indexed), `date` (DateField, indexed)
- `name`, `description`, `calories`, `protein`, `carbs`, `fat`, `basis`, `added_at`

**UserTdee** — one row per user: `user_id` (unique), `tdee` (int)

**ParsedArticle** — scraped forum articles: `title`, `url` (unique), `post_date`, `author`

**AuthorizedUser** / **PushTarget** — access control + push notification targets

## Bot Commands (defined in `Cmd` enum in views.py)

| Command | Description |
|---------|-------------|
| `add {food}` | Log food (AI estimates nutrition). Bare `add` enters pending state |
| `remove [indices]` | Delete entries. Bare `remove` shows today + waits for indices |
| `modify {idx} {text}` | AI re-estimates entry based on modification |
| `today` | Show today's food log |
| `history` | Past 7 days summary |
| `report [question]` | Daily report + AI dietary advice |
| `set tdee {num}` | Set daily calorie target |
| Image message | AI identifies food from photo, logs it |

Chinese aliases: `加`=add, `刪除`=remove, `修改`=modify, `今天`=today, `報告`=report, `歷史`=history

Admin commands (require authorization): `articles`, `db`, `clear`, `adduser`, `removeuser`, `listusers`, `addtarget`, `removetarget`, `listtargets`

## Environment Variables

```
LINE_CHANNEL_ACCESS_TOKEN  # LINE Messaging API
LINE_CHANNEL_SECRET        # LINE webhook signature validation
GEMINI_API_KEY             # Google Gemini API
GITHUB_GIST_TOKEN          # Gist backup read/write
GIST_ID                    # Target Gist ID
CRON_SECRET                # Auth for cron/API endpoints
LIFF_ID                    # LINE Frontend Framework app ID
DJANGO_SECRET_KEY
ALLOWED_HOSTS              # Default: localhost,127.0.0.1
DEBUG                      # Default: True
```

## Key Patterns

- **Pending state**: `_pending_add` / `_pending_remove` dicts track multi-step interactions (Rich Menu tap → wait for next message). Module-level dicts, single-worker only.
- **Gist sync**: Every dietary write operation calls `save_dietary_to_gist()`. On startup, `apps.py` loads from Gist if DB is empty.
- **Gemini fallback**: `_gemini_request()` tries models in order (`gemini-2.5-flash-lite` → `gemini-2.5-flash` → `gemini-2.0-flash-lite`), retrying on 429/500/503/403.
- **`Cmd` enum**: `str, Enum` subclass — use `.value` in f-strings, but `==` and `+` work directly.
- **`_reply()` helper**: `_reply(api, token, text, **kwargs)` wraps the LINE reply boilerplate.

## Deployment

```bash
ssh user@lightsail-ip
cd /path/to/project
./deploy.sh   # git pull, pip install, migrate, collectstatic, restart
```

Rich Menu: `python manage.py setup_richmenu --delete && python manage.py setup_richmenu --create`

## Conventions

- Taiwan timezone (UTC+8) for all date logic
- Food entry indices are 1-based in chat commands, but LIFF API uses Django PKs
- All dietary storage functions do lazy imports of models (circular import avoidance)
- CJK font required on server for Rich Menu image generation (`sudo apt install fonts-noto-cjk`)
