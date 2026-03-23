# Deploy YoYo English Bot on AWS Lightsail

## Why Lightsail?

| | Render Free | EC2 (t3.micro) | **Lightsail (Nano)** |
|---|---|---|---|
| Monthly cost | Free | ~$8.50 | **$3.50** |
| Always on | No (sleeps) | Yes | Yes |
| Persistent disk | No | Yes | Yes |
| Static IP included | No | Extra cost | **Free** |
| Firewall setup | N/A | Security Groups (complex) | **Simple UI** |
| SSL | Auto | DIY (Certbot/ALB) | **Free via Cloudflare Origin Cert** |

---

## Prerequisites

- AWS account
- Your domain on Cloudflare (e.g. `yoyo.club.tw`) — we'll use a subdomain `bot.yoyo.club.tw`
- Your environment variables:
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `LINE_CHANNEL_SECRET`
  - `CRON_SECRET`
  - `GEMINI_API_KEY`
  - `DJANGO_SECRET_KEY`
  - `GITHUB_GIST_TOKEN` / `GIST_ID` (optional — backup only)

---

## Step 1: Create a Lightsail Instance

1. Go to **[AWS Lightsail Console](https://lightsail.aws.amazon.com/)**
2. Click **Create instance**
3. Settings:
   - **Region**: Pick the one closest to your users (e.g. `ap-northeast-1` Tokyo)
   - **Platform**: Linux/Unix
   - **Blueprint**: OS Only → **Ubuntu 24.04 LTS**
   - **Plan**: **$3.50/month** (512 MB RAM, 1 vCPU, 20 GB SSD)
   - **Name**: `yoyo-linebot`
4. Click **Create instance**

---

## Step 2: Attach a Static IP

Without a static IP, the public IP changes every time you stop/start the instance.

1. In Lightsail console → **Networking** tab
2. Click **Create static IP**
3. Attach it to your `yoyo-linebot` instance
4. Note down the IP (e.g. `13.230.xx.xx`)

This is **free** as long as it's attached to a running instance.

---

## Step 3: Open Firewall Ports

In Lightsail console → click your instance → **Networking** tab.

Open these ports on **both IPv4 and IPv6 firewalls**:

| Type | Port | Purpose |
|------|------|---------|
| SSH | 22 | SSH access (default, already open) |
| HTTP | 80 | Redirect to HTTPS |
| HTTPS | 443 | Cloudflare connects here |

---

## Step 4: Set Up Cloudflare

### 4a. DNS Record

1. Go to **Cloudflare Dashboard** → select `yoyo.club.tw` → **DNS**
2. Add a record:

   | Type | Name | Content | Proxy status |
   |------|------|---------|--------------|
   | A | `bot` | `<your-lightsail-static-ip>` | **Proxied** (orange cloud ON) |

### 4b. Generate an Origin Certificate

1. **Cloudflare Dashboard** → **SSL/TLS** → **Origin Server**
2. Click **Create Certificate**
3. Settings:
   - Key type: **RSA (2048)**
   - Hostnames: `*.yoyo.club.tw, yoyo.club.tw`
   - Validity: **15 years**
4. Click **Create**
5. **Copy both the certificate and private key** — you only see the private key once

### 4c. SSL Mode

1. **SSL/TLS** → set mode to **Full**

**What this gives you:**
- LINE → Cloudflare: HTTPS (encrypted)
- Cloudflare → your server: HTTPS (encrypted with Origin Certificate)
- Free DDoS protection
- Hides your real server IP

### 4d. WAF Rule (Allow LINE Webhook)

Cloudflare's bot protection will block LINE's webhook requests. You need to exempt `/callback/`.

1. **Security** → **Bots** → Turn **Bot Fight Mode** OFF
2. **Security** → **WAF** → **Custom rules** → **Create rule**:
   - **Name**: `Skip security for bot endpoints`
   - Click **Edit expression** and paste:
     ```
     (http.request.uri.path eq "/callback/") or (http.request.uri.path eq "/health/")
     ```
   - **Action**: **Skip**
   - Check all: **All remaining custom rules**, **Rate limiting rules**, **All managed rules**, **Bot Fight Mode**

---

## Step 5: SSH into the Instance

**Option A** — Lightsail browser SSH (easiest):
- Click your instance → click **Connect using SSH**

**Option B** — Terminal:
- Download the key from Lightsail console → **Account** → **SSH keys**

```bash
chmod 400 LightsailDefaultKey-ap-northeast-1.pem
ssh -i LightsailDefaultKey-ap-northeast-1.pem ubuntu@<your-static-ip>
```

---

## Step 6: Install System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git nginx
```

---

## Step 7: Install the Origin Certificate

Save the certificate and key you copied from Cloudflare in Step 4b:

```bash
# Save the certificate
sudo nano /etc/ssl/cloudflare-origin.pem
# Paste the certificate, save

# Save the private key
sudo nano /etc/ssl/cloudflare-origin-key.pem
# Paste the private key, save

# Lock down the key file
sudo chmod 600 /etc/ssl/cloudflare-origin-key.pem
```

---

## Step 8: Deploy the Application

```bash
cd /home/ubuntu
git clone https://github.com/<your-username>/yoyo-English.git
cd yoyo-English

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Create .env file
nano .env
```

Paste into `.env`:

```
DEBUG=False
DJANGO_SECRET_KEY=<generate-a-long-random-string>
ALLOWED_HOSTS=bot.yoyo.club.tw
LINE_CHANNEL_ACCESS_TOKEN=<your-token>
LINE_CHANNEL_SECRET=<your-secret>
CRON_SECRET=<your-cron-secret>
GEMINI_API_KEY=<your-gemini-key>
GITHUB_GIST_TOKEN=<your-gist-token>
GIST_ID=<your-gist-id>
```

> Generate a Django secret key:
> `python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`

Continue setup:

```bash
python manage.py migrate
python manage.py collectstatic --no-input

# Load existing data from Gist (if you have prior data)
python manage.py setup_gist --load

# Quick test
gunicorn mylinebot_config.wsgi:application --bind 0.0.0.0:8000
# Ctrl+C after confirming it starts without errors
```

---

## Step 9: Configure Nginx (Reverse Proxy + HTTPS)

```bash
sudo nano /etc/nginx/sites-available/yoyo-linebot
```

Paste:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name bot.yoyo.club.tw;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name bot.yoyo.club.tw;

    ssl_certificate     /etc/ssl/cloudflare-origin.pem;
    ssl_certificate_key /etc/ssl/cloudflare-origin-key.pem;

    location /static/ {
        alias /home/ubuntu/yoyo-English/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and start Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/yoyo-linebot /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default    # remove default site
sudo nginx -t                                  # test config
sudo systemctl restart nginx
sudo systemctl enable nginx
```

---

## Step 10: Set Up Gunicorn as a systemd Service

```bash
sudo nano /etc/systemd/system/yoyo-linebot.service
```

Paste:

```ini
[Unit]
Description=YoYo English LINE Bot (Gunicorn)
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/yoyo-English
EnvironmentFile=/home/ubuntu/yoyo-English/.env
ExecStart=/home/ubuntu/yoyo-English/venv/bin/gunicorn \
    mylinebot_config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 2 \
    --timeout 120
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl start yoyo-linebot
sudo systemctl enable yoyo-linebot
sudo systemctl status yoyo-linebot
```

---

## Step 11: Set Up Cron Jobs

```bash
crontab -e
```

Add:

```cron
# Daily article scrape — 08:00 Taiwan time (00:00 UTC)
0 0 * * * curl -s -X POST http://127.0.0.1:8000/cron/<your-cron-secret>/

# Daily dietary report — 22:00 Taiwan time (14:00 UTC)
0 14 * * * curl -s -X POST http://127.0.0.1:8000/dietary-report/<your-cron-secret>/
```

No keep-alive needed. Lightsail doesn't sleep.

---

## Step 12: Update LINE Webhook URL

1. Go to [LINE Developers Console](https://developers.line.biz/)
2. Select your Messaging API channel
3. **Webhook URL** → set to:
   ```
   https://bot.yoyo.club.tw/callback/
   ```
4. Toggle **Use webhook** → On
5. Click **Verify** — should return success

---

## Step 13: Verify Everything

```bash
# Services running?
sudo systemctl status yoyo-linebot
sudo systemctl status nginx

# Health check (local)
curl http://127.0.0.1:8000/health/

# Health check (via Cloudflare)
curl https://bot.yoyo.club.tw/health/

# Watch logs in real time
sudo journalctl -u yoyo-linebot -f

# Send a test message to your bot in LINE
```

---

## Checking the Database

SQLite lives on disk at `~/yoyo-English/db.sqlite3`. You can query it directly:

```bash
cd ~/yoyo-English

# List all tables
sqlite3 db.sqlite3 ".tables"

# View articles
sqlite3 db.sqlite3 "SELECT id, title, date FROM mylinebot_code_article ORDER BY date DESC LIMIT 10;"

# View food entries (today)
sqlite3 db.sqlite3 "SELECT id, user_id, food_name, calories, created_at FROM mylinebot_code_foodentry WHERE date(created_at) = date('now') ORDER BY created_at;"

# View authorized users
sqlite3 db.sqlite3 "SELECT * FROM mylinebot_code_authorizeduser;"

# View push targets
sqlite3 db.sqlite3 "SELECT * FROM mylinebot_code_pushtarget;"

# View TDEE settings
sqlite3 db.sqlite3 "SELECT * FROM mylinebot_code_usertdee;"

# Interactive mode (run any SQL)
sqlite3 db.sqlite3
# Then type SQL queries, .tables, .schema, .quit
```

Or use Django's shell:

```bash
cd ~/yoyo-English
source venv/bin/activate

python manage.py shell
```

```python
from mylinebot_code.models import Article, FoodEntry, AuthorizedUser, PushTarget
Article.objects.all()
FoodEntry.objects.filter(created_at__date='2026-03-23')
AuthorizedUser.objects.all()
```

---

## Updating the Code

```bash
cd ~/yoyo-English
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --no-input
sudo systemctl restart yoyo-linebot
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| LINE webhook verify fails | `sudo systemctl status yoyo-linebot` — is Gunicorn running? |
| 502 Bad Gateway | Gunicorn crashed — `sudo journalctl -u yoyo-linebot -n 50` |
| Cloudflare 521 error | Nginx not listening on IPv6 — ensure `listen [::]:443 ssl;` is in config |
| Cloudflare 522 error | Server unreachable — check Lightsail firewall has 443 open on both IPv4 & IPv6 |
| Cloudflare 403 error | WAF blocking request — check Security → WAF skip rule for `/callback/` |
| Can't SSH in | Check Lightsail firewall — is port 22 open? |
| Bot doesn't reply | Check `ALLOWED_HOSTS` includes `bot.yoyo.club.tw` |
| Django 400 Bad Request | `ALLOWED_HOSTS` in `.env` doesn't match the domain |
| Cron not firing | `crontab -l` to verify, check system time with `date -u` |
| systemd "No such file" | Paths in `.service` file don't match actual directory name |

---

## Monthly Cost

| Component | Cost |
|-----------|------|
| Lightsail Nano (512 MB, 1 vCPU, 20 GB SSD) | **$3.50** |
| Static IP (attached) | **Free** |
| SSL (Cloudflare Origin Certificate, 15 years) | **Free** |
| Data transfer (first 1 TB) | **Included** |
| Domain subdomain (`bot.yoyo.club.tw`) | **Free** (part of existing domain) |
| **Total** | **$3.50/month** |

---

## Architecture

```
                    Cloudflare (free)           Lightsail ($3.50/mo)
┌───────────┐      ┌───────────────┐      ┌──────────────────────────┐
│ LINE Users │ ──→  │ HTTPS (443)   │ ──→  │  Nginx (443, Origin Cert)│
│            │ ←──  │ Free SSL      │ ←──  │         ↓                │
└───────────┘      │ DDoS protect  │      │  Gunicorn (8000)         │
                    │ WAF skip rule │      │         ↓                │
                    └───────────────┘      │  Django (/callback/)     │
                                           │         ↓                │
                                           │  SQLite (persistent)     │
                                           └──────────────────────────┘

┌───────────┐                              ┌──────────────────────────┐
│ crontab   │ ──── curl POST ────────────→ │  /cron/<secret>/         │
│ (local)   │                              │  /dietary-report/        │
└───────────┘                              └──────────────────────────┘
```

End-to-end encrypted. No Certbot. No keep-alive pings. SQLite persists on disk.
