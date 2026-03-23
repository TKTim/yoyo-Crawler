# Deploy YoYo English Bot on AWS EC2

## Why EC2 over Render Free Tier?

| Problem on Render Free Tier | Solved on EC2 |
|---|---|
| Server sleeps after 15 min idle | EC2 runs 24/7 |
| Ephemeral filesystem (SQLite wiped on deploy) | Persistent disk — SQLite survives reboots |
| Need GitHub Actions keep-alive hack | Not needed |
| Need Gist backup workaround | Optional (still useful as offsite backup) |

---

## Prerequisites

- An AWS account
- A domain or willingness to use the EC2 public IP directly
- Your existing environment variables ready:
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `LINE_CHANNEL_SECRET`
  - `CRON_SECRET`
  - `GEMINI_API_KEY`
  - `GITHUB_GIST_TOKEN` and `GIST_ID` (optional on EC2, but still useful)
  - `DJANGO_SECRET_KEY`

---

## Step 1: Launch an EC2 Instance

1. Go to **AWS Console → EC2 → Launch Instance**
2. Settings:
   - **Name**: `yoyo-linebot`
   - **AMI**: Amazon Linux 2023 (or Ubuntu 24.04 LTS)
   - **Instance type**: `t2.micro` (free tier eligible) or `t3.micro`
   - **Key pair**: Create or select one (you'll need this to SSH in)
   - **Network / Security Group**: Create a new security group with these inbound rules:

     | Type | Port | Source | Purpose |
     |------|------|--------|---------|
     | SSH | 22 | Your IP | SSH access |
     | HTTP | 80 | 0.0.0.0/0 | LINE webhook |
     | HTTPS | 443 | 0.0.0.0/0 | LINE webhook (TLS) |

   - **Storage**: 8 GB gp3 (default is fine)
3. Click **Launch Instance**

> **Note**: LINE webhooks **require HTTPS**. You'll set up HTTPS in Step 5 with Nginx + Certbot (free SSL), or you can put the instance behind an ALB with an ACM certificate.

---

## Step 2: SSH into the Instance

```bash
chmod 400 your-key.pem
ssh -i your-key.pem ec2-user@<your-ec2-public-ip>
# If Ubuntu: ssh -i your-key.pem ubuntu@<your-ec2-public-ip>
```

---

## Step 3: Install Dependencies

### For Amazon Linux 2023:

```bash
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip git nginx
```

### For Ubuntu 24.04:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx
```

---

## Step 4: Deploy the Application

```bash
# Clone the repo
cd /home/ec2-user   # or /home/ubuntu on Ubuntu
git clone https://github.com/<your-username>/yoyo-English.git
cd yoyo-English

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << 'EOF'
DEBUG=False
DJANGO_SECRET_KEY=<generate-a-long-random-string>
ALLOWED_HOSTS=<your-domain-or-ec2-public-ip>
LINE_CHANNEL_ACCESS_TOKEN=<your-token>
LINE_CHANNEL_SECRET=<your-secret>
CRON_SECRET=<your-cron-secret>
GEMINI_API_KEY=<your-gemini-key>
GITHUB_GIST_TOKEN=<your-gist-token>
GIST_ID=<your-gist-id>
EOF

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --no-input

# Load existing data from Gist (if you have prior data)
python manage.py setup_gist --load

# Test that it starts correctly
gunicorn mylinebot_config.wsgi:application --bind 0.0.0.0:8000
# Ctrl+C to stop after confirming it works
```

---

## Step 5: Set Up Nginx as Reverse Proxy + HTTPS

LINE webhooks require HTTPS. Nginx will sit in front of Gunicorn and handle TLS.

### 5a. Configure Nginx

```bash
sudo nano /etc/nginx/conf.d/yoyo-linebot.conf
```

Paste:

```nginx
server {
    listen 80;
    server_name your-domain.com;   # or your EC2 public IP

    location /static/ {
        alias /home/ec2-user/yoyo-English/staticfiles/;
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

```bash
sudo nginx -t          # test config
sudo systemctl start nginx
sudo systemctl enable nginx
```

### 5b. Get a Free SSL Certificate (requires a domain)

If you have a domain pointing to your EC2 IP:

```bash
# Ubuntu
sudo certbot --nginx -d your-domain.com

# Amazon Linux 2023
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Certbot will auto-configure Nginx for HTTPS and set up auto-renewal.

> **No domain?** You can use an **AWS Application Load Balancer (ALB)** with a free ACM certificate instead, or use a free domain from services like freenom/duckdns.

---

## Step 6: Set Up Gunicorn as a systemd Service

This ensures Gunicorn starts automatically on boot and restarts on crash.

```bash
sudo nano /etc/systemd/system/yoyo-linebot.service
```

Paste (adjust paths for Ubuntu if needed):

```ini
[Unit]
Description=YoYo English LINE Bot (Gunicorn)
After=network.target

[Service]
User=ec2-user
Group=ec2-user
WorkingDirectory=/home/ec2-user/yoyo-English
EnvironmentFile=/home/ec2-user/yoyo-English/.env
ExecStart=/home/ec2-user/yoyo-English/venv/bin/gunicorn \
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

# Check status
sudo systemctl status yoyo-linebot
```

---

## Step 7: Set Up Cron Jobs (Replace GitHub Actions)

On EC2 you have a real cron. No more GitHub Actions keep-alive hack.

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

No keep-alive ping needed — EC2 doesn't sleep.

---

## Step 8: Update the LINE Webhook URL

1. Go to [LINE Developers Console](https://developers.line.biz/)
2. Select your Messaging API channel
3. Under **Webhook settings**, set the Webhook URL to:
   ```
   https://your-domain.com/callback/
   ```
4. Make sure **Use webhook** is toggled on
5. Click **Verify** to confirm it works

---

## Step 9: Verify Everything

```bash
# Check Gunicorn is running
sudo systemctl status yoyo-linebot

# Check Nginx is running
sudo systemctl status nginx

# Check logs
sudo journalctl -u yoyo-linebot -f          # Gunicorn logs
sudo tail -f /var/log/nginx/error.log        # Nginx logs

# Test the health endpoint
curl http://127.0.0.1:8000/health/

# Test from outside (after HTTPS is set up)
curl https://your-domain.com/health/
```

---

## Updating the Code

When you push new changes to GitHub:

```bash
cd /home/ec2-user/yoyo-English
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --no-input
sudo systemctl restart yoyo-linebot
```

---

## Cost

| Component | Cost |
|-----------|------|
| `t2.micro` EC2 | **Free** for 12 months (AWS free tier), then ~$8.50/month |
| 8 GB EBS storage | **Free** for 12 months, then ~$0.64/month |
| SSL certificate (Certbot) | **Free** |
| Data transfer (first 100 GB/month) | **Free** |
| **Total after free tier** | **~$9/month** |

> For the cheapest long-term option, buy a **Reserved Instance** (1 year, `t3.micro`) for ~$3.50/month, or use a **Spot Instance** if you're comfortable with occasional interruptions.

---

## Architecture on EC2

```
                                     EC2 Instance
┌───────────┐   HTTPS POST     ┌──────────────────────────────┐
│ LINE Users │ ──────────────→  │  Nginx (port 443, TLS)       │
│            │ ←──────────────  │        ↓                     │
└───────────┘                   │  Gunicorn (port 8000)        │
                                │        ↓                     │
                                │  Django App (/callback/)     │
                                │        ↓                     │
                                │  SQLite (persistent disk!)   │
                                └──────────────────────────────┘

┌──────────────┐                ┌──────────────────────────────┐
│ crontab      │ ─curl POST──→ │  /cron/<secret>/             │
│ (on the EC2) │               │  /dietary-report/<secret>/   │
└──────────────┘                └──────────────────────────────┘
```

No more Gist workaround for persistence. No more keep-alive pings. SQLite lives on the EBS volume and survives reboots.
