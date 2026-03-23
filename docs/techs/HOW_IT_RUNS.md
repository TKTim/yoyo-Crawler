# How This Service Runs

## What Kind of Service Is This?

This is a **Django-based LINE messaging bot** that serves two purposes:

1. **English Article Curation** — Scrapes weekly English learning articles from the [YoYo Club forum](https://yoyo.club.tw/viewforum.php?f=2) and pushes them to LINE users.
2. **Dietary Tracking** — Logs food entries with AI-powered nutrition estimation (Google Gemini), supports photo-based food recognition, and generates daily dietary reports.

The bot is a **webhook-driven web service**: it doesn't poll LINE for messages. Instead, LINE's servers send HTTP POST requests to the bot whenever a user sends a message. The bot processes the message and responds via the LINE Messaging API.

### Tech Stack

| Component | Technology |
|-----------|------------|
| Web Framework | Django |
| WSGI Server | Gunicorn |
| Messaging Platform | LINE Messaging API (SDK v3) |
| AI / LLM | Google Gemini (`gemini-2.5-flash-lite` with fallback chain) |
| Database | SQLite3 |
| Persistent Storage | GitHub Gist (backup for ephemeral filesystem) |
| Hosting | Render (free tier) |
| Automation | GitHub Actions (cron jobs, keep-alive) |

---

## How It Runs on Render and Keeps Listening to LINE

### 1. The Server Process

When Render deploys the service, it runs:

```bash
python manage.py migrate && gunicorn mylinebot_config.wsgi:application
```

This starts **Gunicorn**, a production WSGI HTTP server, which binds to the port Render assigns. Gunicorn keeps the process alive and listens for incoming HTTP requests — it doesn't exit after handling one request.

The key endpoint is `/callback/`, which is registered as the **LINE webhook URL**. When a user sends a message in LINE:

```
User sends message in LINE
        ↓
LINE Platform sends POST to https://<your-app>.onrender.com/callback/
        ↓
Gunicorn receives the request
        ↓
Django routes it to the callback view
        ↓
LINE SDK validates the signature and dispatches to the handler
        ↓
Bot processes the command and replies via LINE API
```

### 2. Keeping the Server Awake

Render's free tier **spins down** the service after ~15 minutes of inactivity. A sleeping service takes 30–60 seconds to wake up on the next request, which means LINE webhook deliveries can time out.

**Solution**: A GitHub Actions workflow pings the `/health/` endpoint every 13 minutes to keep the server awake.

```yaml
# .github/workflows/keep-alive.yml
schedule:
  - cron: '*/13 * * * *'   # Every 13 minutes
```

This `/health/` endpoint returns a simple `200 OK` — just enough to reset Render's inactivity timer.

### 3. Scheduled Tasks via GitHub Actions

Since Render's free tier doesn't support background workers or cron jobs, **GitHub Actions** handles all scheduled tasks by calling protected API endpoints:

| Schedule | Workflow | Endpoint | Purpose |
|----------|----------|----------|---------|
| Every 13 min | `keep-alive.yml` | `GET /health/` | Prevent Render from sleeping |
| Daily 08:00 CST | `daily-scraper.yml` | `POST /cron/<secret>/` | Scrape forum articles and push to LINE |
| Daily 22:00 CST | `daily-dietary-report.yml` | `POST /dietary-report/<secret>/` | Send daily dietary summary to users |

All cron endpoints are protected by a `CRON_SECRET` environment variable — only requests with the correct secret in the URL are accepted.

### 4. Data Persistence on Ephemeral Storage

Render's free tier has an **ephemeral filesystem** — the SQLite database is wiped on every deploy or restart.

**Workaround**: The service uses **GitHub Gist as a backup store**.

- **On every write** (new article, new food entry, user change): the data is saved to both SQLite and a GitHub Gist via the API.
- **On startup** (`build.sh`): if the database is empty, it loads data from the Gist backup.

Gist files used:
- `yoyo_articles.json` — Article database
- `yoyo_authorized_users.json` — Authorized user list
- `yoyo_push_targets.json` — Push notification targets
- `yoyo_dietary_logs.json` — Food entries and TDEE settings

---

## Architecture Diagram

```
┌─────────────┐     Webhook POST      ┌──────────────────────┐
│  LINE Users  │ ──────────────────→   │   Render             │
│  (Messages   │                       │   ┌────────────────┐ │
│   & Photos)  │ ←──────────────────   │   │  Gunicorn      │ │
│              │   LINE Messaging API  │   │  + Django      │ │
└─────────────┘                        │   │  /callback/    │ │
                                       │   └───────┬────────┘ │
                                       │           │          │
                                       │   ┌───────▼────────┐ │
                                       │   │   SQLite DB    │ │
                                       │   └───────┬────────┘ │
                                       └───────────┼──────────┘
                                                   │
                                          Sync on write / Restore on boot
                                                   │
                                       ┌───────────▼──────────┐
                                       │   GitHub Gist        │
                                       │   (Persistent JSON)  │
                                       └──────────────────────┘

┌─────────────────┐    HTTP POST       ┌──────────────────────┐
│  GitHub Actions  │ ─────────────→    │   /cron/<secret>/    │
│  (Cron triggers  │                   │   /dietary-report/   │
│   & Keep-alive)  │                   │   /health/           │
└─────────────────┘                    └──────────────────────┘

┌─────────────────┐    API Call        ┌──────────────────────┐
│  Google Gemini   │ ←────────────     │   Nutrition estimate │
│  (AI Model)      │ ────────────→    │   & food recognition │
└─────────────────┘                    └──────────────────────┘
```

---

## Summary

This service stays alive on Render by:

1. **Gunicorn** keeps a long-running HTTP server process — it doesn't exit.
2. **LINE webhooks** push messages to `/callback/` — the bot is always passively listening, not polling.
3. **GitHub Actions keep-alive** pings `/health/` every 13 minutes to prevent Render's free tier from sleeping.
4. **GitHub Gist** acts as a durable data store to survive Render's ephemeral filesystem resets.

It's a **webhook-driven, event-based service** — not a daemon that polls. The server just waits for incoming HTTP requests, processes them, and responds. Render and Gunicorn handle keeping the process alive; GitHub Actions handles keeping Render from putting it to sleep.
