# AWS Lightsail to EC2 Migration Guide

Complete step-by-step guide for migrating the YoYo English LINE Bot from AWS Lightsail to EC2 (Ubuntu 22.04, t2.medium).

## Table of Contents

1. [Pre-Migration Checklist](#pre-migration-checklist)
2. [EC2 Instance Setup](#1-ec2-instance-setup)
3. [Server Provisioning](#2-server-provisioning-ubuntu-2204)
4. [Project Deployment](#3-project-deployment)
5. [Gunicorn Setup](#4-gunicorn-setup)
6. [Nginx Configuration](#5-nginx-configuration)
7. [IPv6, Domain & SSL Setup](#6-ipv6-domain--ssl-setup)
8. [LINE Bot Configuration](#7-line-bot-configuration)
9. [Cron Jobs](#8-cron-jobs-setup)
10. [Deploy Script Update](#9-deploy-script-update)
11. [Data Migration & Verification](#10-data-migration--verification)
12. [Monitoring & Maintenance](#11-monitoring--maintenance)
13. [Rollback Plan](#12-rollback-plan)

---

## Pre-Migration Checklist

Before starting, gather the following:

- [ ] Your current `.env` file from Lightsail (contains all secrets)
- [ ] Your domain name (e.g., `bot.yoyo.club.tw`)
- [ ] Access to your DNS provider (Cloudflare, Route53, etc.)
- [ ] LINE Developer Console access
- [ ] Verify Gist backup has latest data (auto-synced on every write)
- [ ] Note your current webhook URL in LINE Console

**Environment variables you'll need:**
```bash
DEBUG=False
DJANGO_SECRET_KEY=<your-secret-key>
ALLOWED_HOSTS=<your-domain>
LINE_CHANNEL_ACCESS_TOKEN=<your-token>
LINE_CHANNEL_SECRET=<your-secret>
LIFF_ID=<your-liff-id>
CRON_SECRET=<your-cron-secret>
GEMINI_API_KEY=<your-gemini-key>
GITHUB_GIST_TOKEN=<your-gist-token>
GIST_ID=<your-gist-id>
```

---

## 1. EC2 Instance Setup

### 1.1 Launch EC2 Instance

1. Go to **AWS Console** → **EC2** → **Launch Instance**

2. Configure instance:
   ```
   Name: yoyo-linebot
   AMI: Ubuntu Server 22.04 LTS (HVM), SSD Volume Type
   Architecture: 64-bit (x86)
   Instance type: t2.medium (2 vCPU, 4 GiB RAM)
   ```

3. **Key pair (login)**:
   - Create new key pair OR use existing
   - Key pair name: `yoyo-linebot-ec2`
   - Key pair type: RSA
   - Private key file format: `.pem`
   - **Download and save the .pem file securely**

4. **Network settings** → Click **Edit**:
   - VPC: Default VPC (or your custom VPC)
   - Subnet: No preference (auto-assign)
   - Auto-assign public IP: **Enable**
   - Firewall (Security groups): Create new security group
     - Security group name: `yoyo-linebot-sg`
     - Description: `Security group for YoYo English LINE bot`

5. **Inbound security group rules** (add all three):

   | Type  | Protocol | Port Range | Source Type | Source      | Description         |
   |-------|----------|------------|-------------|-------------|---------------------|
   | SSH   | TCP      | 22         | My IP       | <your-ip>   | SSH access          |
   | HTTP  | TCP      | 80         | Anywhere    | 0.0.0.0/0   | HTTP redirect to HTTPS |
   | HTTPS | TCP      | 443        | Anywhere    | 0.0.0.0/0   | LINE webhook        |

   **Add IPv6 rules** (click **Add rule** for each):

   | Type  | Protocol | Port Range | Source Type | Source      |
   |-------|----------|------------|-------------|-------------|
   | HTTP  | TCP      | 80         | Anywhere IPv6 | ::/0      |
   | HTTPS | TCP      | 443        | Anywhere IPv6 | ::/0      |

6. **Configure storage**:
   ```
   Volume type: gp3
   Size: 20 GiB (more than enough for SQLite + logs)
   Delete on termination: No (protect your data)
   Encrypted: Yes (recommended)
   ```

7. **Advanced details** (expand):
   - No changes needed (defaults are fine)

8. Click **Launch instance**

### 1.2 Allocate Elastic IP

EC2 instances get a new public IP every time they restart. Fix this with an Elastic IP.

```bash
# In AWS Console:
# EC2 → Elastic IPs → Allocate Elastic IP address
```

1. Click **Allocate Elastic IP address**
2. Network Border Group: Keep default
3. Public IPv4 address pool: Amazon's pool
4. Click **Allocate**
5. Select the new Elastic IP → **Actions** → **Associate Elastic IP address**
6. Instance: Select `yoyo-linebot`
7. Private IP: Select the instance's private IP
8. Click **Associate**

**Note down your Elastic IP** (e.g., `13.230.xx.xx`) — this is your permanent server IP.

### 1.3 SSH Key Setup

```bash
# On your local machine
chmod 400 ~/Downloads/yoyo-linebot-ec2.pem

# Test SSH connection (replace with your Elastic IP)
ssh -i ~/Downloads/yoyo-linebot-ec2.pem ubuntu@13.230.xx.xx

# Optional: Add to ~/.ssh/config for easier access
cat >> ~/.ssh/config << 'EOF'
Host yoyo-ec2
    HostName 13.230.xx.xx
    User ubuntu
    IdentityFile ~/Downloads/yoyo-linebot-ec2.pem
    ServerAliveInterval 60
EOF

# Now you can just: ssh yoyo-ec2
```

---

## 2. Server Provisioning (Ubuntu 22.04)

SSH into your new EC2 instance:

```bash
ssh -i ~/Downloads/yoyo-linebot-ec2.pem ubuntu@13.230.xx.xx
```

### 2.1 System Updates

```bash
sudo apt update && sudo apt upgrade -y
```

### 2.2 Install Python 3.10

Ubuntu 22.04 comes with Python 3.10 by default, but install the full set:

```bash
sudo apt install -y python3.10 python3.10-venv python3-pip
python3 --version  # Should show Python 3.10.x
```

### 2.3 Install Nginx

```bash
sudo apt install -y nginx
sudo systemctl enable nginx
```

### 2.4 Install CJK Fonts

Required for Rich Menu image generation with Pillow:

```bash
sudo apt install -y fonts-noto-cjk fonts-noto-cjk-extra
```

Verify fonts are installed:

```bash
fc-list | grep -i noto | grep -i cjk
# Should show multiple Noto CJK fonts
```

### 2.5 Install Git

```bash
sudo apt install -y git
git --version
```

### 2.6 Create Application User (Optional but Recommended)

For production, it's best practice to run the app as a non-root user. Since we're already using `ubuntu`, we'll stick with it. But here's how you'd create a dedicated user:

```bash
# Optional: create dedicated app user
sudo useradd -m -s /bin/bash yoyobot
sudo usermod -aG sudo yoyobot

# Then switch to that user for deployment
sudo su - yoyobot
```

For this guide, we'll continue with the `ubuntu` user.

### 2.8 Configure Firewall (UFW - Optional)

EC2 security groups already handle firewall rules, but you can add UFW as an extra layer:

```bash
# Optional: UFW setup
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw --force enable
sudo ufw status
```

---

## 3. Project Deployment

### 3.1 Clone Repository

```bash
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/yoyo-Crawler.git
cd yoyo-Crawler
```

**Replace `YOUR_USERNAME`** with your actual GitHub username.

If the repo is private:

```bash
# Generate SSH key on EC2
ssh-keygen -t ed25519 -C "ec2-yoyo-linebot"
cat ~/.ssh/id_ed25519.pub
# Copy the output and add it to GitHub: Settings → SSH and GPG keys → New SSH key

# Then clone via SSH
git clone git@github.com:YOUR_USERNAME/yoyo-Crawler.git
```

### 3.2 Create Virtual Environment

```bash
cd /home/ubuntu/yoyo-Crawler
python3 -m venv venv
source venv/bin/activate

# Verify you're in the venv
which python  # Should show: /home/ubuntu/yoyo-Crawler/venv/bin/python
```

### 3.3 Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Expected packages (from requirements.txt):
- Django 5.1.4
- gunicorn 21.2.0
- line-bot-sdk 3.21.0
- Pillow 11.2.1
- whitenoise 6.6.0
- python-dotenv 1.2.1
- boto3, requests, beautifulsoup4, etc.

### 3.4 Create .env File

**Method 1: Copy from Lightsail**

If you have the `.env` file from your Lightsail instance:

```bash
# On your local machine
scp -i ~/Downloads/yoyo-linebot-ec2.pem /path/to/lightsail/.env ubuntu@13.230.xx.xx:/home/ubuntu/yoyo-Crawler/.env
```

**Method 2: Create manually**

```bash
nano /home/ubuntu/yoyo-Crawler/.env
```

Paste and fill in your values:

```bash
DEBUG=False
DJANGO_SECRET_KEY=your-django-secret-key-here
ALLOWED_HOSTS=bot.yoyo.club.tw,13.230.xx.xx
LINE_CHANNEL_ACCESS_TOKEN=your-line-token
LINE_CHANNEL_SECRET=your-line-secret
LIFF_ID=your-liff-id
CRON_SECRET=your-cron-secret
GEMINI_API_KEY=your-gemini-api-key
GITHUB_GIST_TOKEN=your-github-token
GIST_ID=your-gist-id
LOG_LEVEL=INFO
```

**Generate a new Django secret key** if you don't have one:

```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 3.5 Run Django Migrations

```bash
source /home/ubuntu/yoyo-Crawler/venv/bin/activate
cd /home/ubuntu/yoyo-Crawler
python manage.py migrate
```

Expected output:
```
Running migrations:
  Applying contenttypes.0001_initial... OK
  Applying auth.0001_initial... OK
  Applying mylinebot_code.0001_initial... OK
  ...
```

### 3.6 Collect Static Files

```bash
python manage.py collectstatic --no-input --clear
```

Creates `/home/ubuntu/yoyo-Crawler/staticfiles/` with all static assets.

### 3.7 Load Data from Gist Backup

Your Lightsail instance syncs data to Gist on every write. Restore it:

```bash
python manage.py setup_gist --load
```

Expected output:
```
Loading data from Gist...
Loaded 42 articles
Loaded 3 authorized users
Loaded 2 push targets
Loaded 156 food entries
Loaded 2 user TDEEs
```

If this fails, the database will be empty (but the app will still work).

### 3.8 Test Gunicorn

```bash
gunicorn mylinebot_config.wsgi:application --bind 0.0.0.0:8000
```

Open another terminal and test:

```bash
ssh yoyo-ec2
curl http://127.0.0.1:8000/health/
```

Expected response: `{"status": "ok"}`

Press `Ctrl+C` to stop Gunicorn. We'll set it up as a systemd service next.

---

## 4. Gunicorn Setup

### 4.1 Create systemd Service File

```bash
sudo nano /etc/systemd/system/yoyo-linebot.service
```

Paste the following configuration:

```ini
[Unit]
Description=YoYo English LINE Bot (Gunicorn)
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/yoyo-Crawler
EnvironmentFile=/home/ubuntu/yoyo-Crawler/.env

# Gunicorn command
ExecStart=/home/ubuntu/yoyo-Crawler/venv/bin/gunicorn \
    mylinebot_config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 3 \
    --worker-class sync \
    --timeout 120 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --access-logfile /home/ubuntu/yoyo-Crawler/logs/gunicorn-access.log \
    --error-logfile /home/ubuntu/yoyo-Crawler/logs/gunicorn-error.log \
    --log-level info

# Restart policy
Restart=always
RestartSec=3

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Worker Configuration for t2.medium (2 vCPU, 4GB RAM):**
- `--workers 3`: Recommended formula is `(2 × CPU cores) + 1 = 5`, but 3 is safer for 4GB RAM
- `--worker-class sync`: Default synchronous workers (good for Django)
- `--timeout 120`: 2 minutes for slow Gemini API calls
- `--max-requests 1000`: Recycle workers every 1000 requests (prevents memory leaks)

### 4.2 Create Log Directory

```bash
mkdir -p /home/ubuntu/yoyo-Crawler/logs
```

### 4.3 Enable and Start Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable yoyo-linebot
sudo systemctl start yoyo-linebot
```

### 4.4 Check Service Status

```bash
sudo systemctl status yoyo-linebot
```

Expected output:

```
● yoyo-linebot.service - YoYo English LINE Bot (Gunicorn)
     Loaded: loaded (/etc/systemd/system/yoyo-linebot.service; enabled)
     Active: active (running) since Sun 2026-03-30 12:00:00 UTC; 5s ago
   Main PID: 12345 (gunicorn)
      Tasks: 4 (limit: 4915)
     Memory: 120.5M
```

If it fails:

```bash
# View detailed logs
sudo journalctl -u yoyo-linebot -n 50 --no-pager

# Check for errors
sudo journalctl -u yoyo-linebot -f
```

Common issues:
- `.env` file not found → Check path in service file
- Python module errors → Check venv activation path
- Permission denied → Check file ownership: `ls -la /home/ubuntu/yoyo-Crawler`

---

## 5. Nginx Configuration

### 5.1 Create Nginx Site Configuration

```bash
sudo nano /etc/nginx/sites-available/yoyo-linebot
```

Paste (replace `bot.yoyo.club.tw` with your domain):

```nginx
# HTTP server - redirect to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name bot.yoyo.club.tw;

    # Redirect all traffic to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS server (Cloudflare Origin Certificate)
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name bot.yoyo.club.tw;

    # Cloudflare Origin Certificate (15-year validity, no renewal needed)
    ssl_certificate     /etc/ssl/cloudflare-origin.pem;
    ssl_certificate_key /etc/ssl/cloudflare-origin-key.pem;

    # Client max body size (for image uploads via LINE)
    client_max_body_size 10M;

    # Static files
    location /static/ {
        alias /home/ubuntu/yoyo-Crawler/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Proxy to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;

        # Timeouts for slow Gemini API calls
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }
}
```

### 5.2 Enable Site and Remove Default

```bash
# Enable the site
sudo ln -s /etc/nginx/sites-available/yoyo-linebot /etc/nginx/sites-enabled/

# Remove default site (optional but recommended)
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t
```

Expected output:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### 5.3 Restart Nginx

```bash
sudo systemctl restart nginx
sudo systemctl status nginx
```

### 5.4 Test HTTP Access

```bash
# From the EC2 instance
curl http://127.0.0.1/health/
curl http://bot.yoyo.club.tw/health/  # If DNS is already set up
```

---

## 6. IPv6, Domain & SSL Setup

### 6.1 Enable IPv6 on EC2

Cloudflare may connect to your server via IPv6. You need to enable it on your VPC, subnet, and instance.

#### 6.1.1 Add IPv6 CIDR to VPC

1. **AWS Console** → **VPC** → **Your VPCs**
2. Select your VPC → **Actions** → **Edit CIDRs**
3. Click **Add new IPv6 CIDR**
4. Select **Amazon-provided IPv6 CIDR block**
5. Click **Select CIDR**, then **Save**

#### 6.1.2 Add IPv6 CIDR to Subnet

1. **VPC** → **Subnets** → Select the subnet your EC2 instance is in
2. **Actions** → **Edit IPv6 CIDRs**
3. Click **Add IPv6 CIDR**
4. AWS will auto-suggest a `/64` block — accept it
5. Click **Save**

#### 6.1.3 Update Route Table

1. **VPC** → **Route Tables** → Select the route table for your subnet
2. **Routes** tab → **Edit routes**
3. **Add route**:
   ```
   Destination: ::/0
   Target: igw-xxxxxxxx (your Internet Gateway)
   ```
4. Click **Save changes**

#### 6.1.4 Assign IPv6 Address to Instance

1. **EC2** → **Instances** → Select your instance
2. **Actions** → **Networking** → **Manage IP addresses**
3. Under the network interface, find **IPv6 addresses**
4. Click **Assign new IP address** (auto-assign)
5. Click **Save**

#### 6.1.5 Verify IPv6

```bash
# On the EC2 instance
ip -6 addr show
# Should show a global IPv6 address (2600:... or similar)
```

#### 6.1.6 Add AAAA Record in Cloudflare (Optional)

If you want Cloudflare to connect via IPv6:

1. **Cloudflare** → **DNS** → **Records**
2. Add record:
   ```
   Type: AAAA
   Name: bot
   IPv6 address: <your-ec2-ipv6-address>
   Proxy status: Proxied (orange cloud ON)
   ```

### 6.2 Set Up Cloudflare DNS

1. Log in to **Cloudflare Dashboard** → select `yoyo.club.tw` → **DNS**
2. Add or update A record:

   | Type | Name | Content | Proxy status |
   |------|------|---------|--------------|
   | A | `bot` | `<your-elastic-ip>` | **Proxied** (orange cloud ON) |

**Important:** Keep Cloudflare proxy ON (orange cloud). We use a Cloudflare Origin Certificate, so the proxy must stay enabled.

### 6.3 Generate Cloudflare Origin Certificate

1. **Cloudflare Dashboard** → **SSL/TLS** → **Origin Server**
2. Click **Create Certificate**
3. Settings:
   - Key type: **RSA (2048)**
   - Hostnames: `*.yoyo.club.tw, yoyo.club.tw`
   - Validity: **15 years**
4. Click **Create**
5. **Copy both the certificate and private key** — you only see the private key once

### 6.4 Install Origin Certificate on Server

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

### 6.5 Set Cloudflare SSL Mode

1. **SSL/TLS** → set mode to **Full**

**What this gives you:**
- LINE → Cloudflare: HTTPS (Cloudflare's universal SSL)
- Cloudflare → your server: HTTPS (encrypted with Origin Certificate)
- Free DDoS protection
- Hides your real server IP
- No certificate renewal needed (15-year validity)

### 6.6 Configure Cloudflare WAF (Allow LINE Webhook)

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

### 6.7 Restart Nginx with SSL

```bash
# Test config
sudo nginx -t

# Restart
sudo systemctl restart nginx
```

### 6.8 Verify SSL

```bash
# Test HTTPS via Cloudflare
curl https://bot.yoyo.club.tw/health/
# Expected: {"status": "ok"}
```

**Note:** Since we use a Cloudflare Origin Certificate (not a publicly trusted CA), direct `openssl s_client` to the server will show certificate warnings. This is expected — the certificate is only valid when traffic goes through Cloudflare's proxy.

---

## 7. LINE Bot Configuration

### 7.1 Update Webhook URL

1. Go to [LINE Developers Console](https://developers.line.biz/console/)
2. Select your provider → Select your Messaging API channel
3. Go to **Messaging API** tab
4. Scroll to **Webhook settings**
5. **Webhook URL**: Update to:
   ```
   https://bot.yoyo.club.tw/callback/
   ```
6. Click **Update**
7. Click **Verify** button

Expected result: ✓ Success

If verification fails:
- Check Nginx and Gunicorn are running: `sudo systemctl status nginx yoyo-linebot`
- Check logs: `sudo journalctl -u yoyo-linebot -f`
- Verify DNS points to EC2: `nslookup bot.yoyo.club.tw`
- Verify SSL works: `curl https://bot.yoyo.club.tw/health/`
- Check ALLOWED_HOSTS in `.env` includes your domain

### 7.2 Update LIFF Endpoint URL (if using LIFF)

1. LINE Developers Console → Your channel → **LIFF** tab
2. Edit your LIFF app
3. **Endpoint URL**: Update to:
   ```
   https://bot.yoyo.club.tw/liff/editor/
   ```
4. Click **Update**

### 7.3 Test the Bot

Send a message to your LINE bot:

```
今天
```

Expected response: Today's food log or empty state message.

Try adding food:

```
add 雞胸肉 200g
```

Expected: AI estimates nutrition and adds entry.

Check logs if there are issues:

```bash
sudo journalctl -u yoyo-linebot -f
```

---

## 8. Cron Jobs Setup

### 8.1 Open Crontab Editor

```bash
crontab -e
```

If prompted for editor, choose `nano` (1) or `vim` (2).

### 8.2 Add Cron Jobs

Paste the following (replace `<your-cron-secret>` with your actual CRON_SECRET from `.env`):

```cron
# YoYo English LINE Bot - Cron Jobs

# Daily article scrape from forum — 08:00 Taiwan time (00:00 UTC)
# Fetches new English articles from yoyo.club.tw forum
0 0 * * * curl -s -X POST http://127.0.0.1:8000/cron/<your-cron-secret>/ >> /home/ubuntu/yoyo-Crawler/logs/cron-articles.log 2>&1

# Daily dietary report push — 22:00 Taiwan time (14:00 UTC)
# Sends nutrition summary to all PushTarget users
0 14 * * * curl -s -X POST http://127.0.0.1:8000/dietary-report/<your-cron-secret>/ >> /home/ubuntu/yoyo-Crawler/logs/cron-dietary.log 2>&1
```

Save and exit (`Ctrl+X`, then `Y`, then `Enter`).

### 8.3 Verify Cron Jobs

```bash
crontab -l
```

Should show your two cron jobs.

### 8.4 Test Cron Jobs Manually

```bash
# Test article scrape
curl -X POST http://127.0.0.1:8000/cron/<your-cron-secret>/

# Test dietary report
curl -X POST http://127.0.0.1:8000/dietary-report/<your-cron-secret>/
```

Check logs:

```bash
tail -f /home/ubuntu/yoyo-Crawler/logs/cron-articles.log
tail -f /home/ubuntu/yoyo-Crawler/logs/cron-dietary.log
```

### 8.5 Verify System Timezone

Cron uses UTC by default. Verify:

```bash
date
# Should show UTC time

timedatectl
# Should show: Time zone: Etc/UTC (UTC, +0000)
```

Your cron times should be in UTC:
- 08:00 Taiwan (UTC+8) = 00:00 UTC ✓
- 22:00 Taiwan (UTC+8) = 14:00 UTC ✓

---

## 9. Deploy Script Update

Your existing `deploy.sh` should work on EC2 with minimal changes. Let's verify and update if needed.

### 9.1 Current deploy.sh

Your current script:

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "=== Pulling latest code ==="
git pull origin main
echo "=== Installing dependencies ==="
source venv/bin/activate
pip install -r requirements.txt --quiet
echo "=== Running migrations ==="
python manage.py migrate --verbosity 0
echo "=== Collecting static files ==="
python manage.py collectstatic --no-input --clear --verbosity 0
echo "=== Restarting service ==="
sudo systemctl restart yoyo-linebot
echo "=== Done ==="
sudo systemctl status yoyo-linebot --no-pager
```

This script already works perfectly for EC2. No changes needed.

### 9.2 Make It Executable (if not already)

```bash
chmod +x /home/ubuntu/yoyo-Crawler/deploy.sh
```

### 9.3 Test Deploy Script

```bash
cd /home/ubuntu/yoyo-Crawler
./deploy.sh
```

Expected output:

```
=== Pulling latest code ===
Already up to date.
=== Installing dependencies ===
=== Running migrations ===
=== Collecting static files ===
=== Restarting service ===
=== Done ===
● yoyo-linebot.service - YoYo English LINE Bot (Gunicorn)
     Loaded: loaded
     Active: active (running)
```

### 9.4 Set Up Sudo Without Password (Optional)

To avoid password prompt when running `deploy.sh`:

```bash
sudo visudo
```

Add at the bottom:

```
# Allow ubuntu user to restart yoyo-linebot without password
ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart yoyo-linebot
ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl status yoyo-linebot
ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
```

Save and exit (`Ctrl+X`, then `Y`, then `Enter`).

Now `./deploy.sh` runs without password prompts.

---

## 10. Data Migration & Verification

The app uses GitHub Gist for automatic backup. On startup, if the database is empty, it auto-restores from Gist.

### 10.1 Verify Data Restoration

```bash
cd /home/ubuntu/yoyo-Crawler
source venv/bin/activate

# Check database tables
sqlite3 db.sqlite3 ".tables"
```

Expected output:

```
auth_group                      mylinebot_code_foodentry
auth_group_permissions          mylinebot_code_parsedarticle
auth_permission                 mylinebot_code_pushtarget
auth_user                       mylinebot_code_usertdee
django_content_type             mylinebot_code_userprofile
django_migrations               django_session
mylinebot_code_authorizeduser
```

### 10.2 Check Data Counts

```bash
sqlite3 db.sqlite3 << 'EOF'
.mode column
.headers on
SELECT 'Articles' as table_name, COUNT(*) as count FROM mylinebot_code_parsedarticle
UNION ALL
SELECT 'Authorized Users', COUNT(*) FROM mylinebot_code_authorizeduser
UNION ALL
SELECT 'Push Targets', COUNT(*) FROM mylinebot_code_pushtarget
UNION ALL
SELECT 'Food Entries', COUNT(*) FROM mylinebot_code_foodentry
UNION ALL
SELECT 'User TDEEs', COUNT(*) FROM mylinebot_code_usertdee;
EOF
```

Expected output (your numbers will vary):

```
table_name         count
-----------------  -----
Articles           42
Authorized Users   3
Push Targets       2
Food Entries       156
User TDEEs         2
```

### 10.3 View Recent Food Entries

```bash
sqlite3 db.sqlite3 << 'EOF'
.mode column
.headers on
SELECT user_id, date, name, calories, protein, carbs, fat
FROM mylinebot_code_foodentry
ORDER BY added_at DESC
LIMIT 5;
EOF
```

### 10.4 Verify Authorized Users

```bash
sqlite3 db.sqlite3 "SELECT user_id FROM mylinebot_code_authorizeduser;"
```

These are the LINE user IDs allowed to use admin commands.

### 10.5 Manual Gist Sync (if needed)

If data didn't auto-restore, manually trigger it:

```bash
python manage.py setup_gist --load
```

Or manually backup current data to Gist:

```bash
python manage.py setup_gist --save
```

---

## 11. Monitoring & Maintenance

### 11.1 CloudWatch Basics (Optional)

EC2 instances send basic metrics to CloudWatch automatically:
- CPU utilization
- Network in/out
- Disk read/write

Access via: **AWS Console** → **CloudWatch** → **Metrics** → **EC2** → **Per-Instance Metrics**

For detailed logs, you can set up the CloudWatch agent (advanced, not covered here).

### 11.2 System Logs

**Gunicorn application logs:**

```bash
# Real-time logs
sudo journalctl -u yoyo-linebot -f

# Last 100 lines
sudo journalctl -u yoyo-linebot -n 100 --no-pager

# Logs from the last hour
sudo journalctl -u yoyo-linebot --since "1 hour ago"

# Search for errors
sudo journalctl -u yoyo-linebot | grep -i error
```

**Nginx logs:**

```bash
# Access logs
sudo tail -f /var/log/nginx/access.log

# Error logs
sudo tail -f /var/log/nginx/error.log

# Gunicorn access/error logs (if configured)
tail -f /home/ubuntu/yoyo-Crawler/logs/gunicorn-access.log
tail -f /home/ubuntu/yoyo-Crawler/logs/gunicorn-error.log
```

**Django application logs:**

```bash
tail -f /home/ubuntu/yoyo-Crawler/scraper.log
```

### 11.3 Log Rotation

Set up automatic log rotation to prevent disk from filling up:

```bash
sudo nano /etc/logrotate.d/yoyo-linebot
```

Paste:

```
/home/ubuntu/yoyo-Crawler/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0644 ubuntu ubuntu
    sharedscripts
    postrotate
        systemctl reload yoyo-linebot > /dev/null 2>&1 || true
    endscript
}
```

Save and exit.

Test log rotation:

```bash
sudo logrotate -d /etc/logrotate.d/yoyo-linebot  # Dry run
sudo logrotate -f /etc/logrotate.d/yoyo-linebot  # Force rotation
```

### 11.4 Systemd Journal Management

Limit systemd journal size:

```bash
sudo nano /etc/systemd/journald.conf
```

Uncomment and set:

```
SystemMaxUse=500M
SystemMaxFileSize=100M
```

Restart journald:

```bash
sudo systemctl restart systemd-journald
```

### 11.5 Disk Space Monitoring

Check disk usage:

```bash
df -h
```

Monitor database size:

```bash
du -h /home/ubuntu/yoyo-Crawler/db.sqlite3
```

Set up a simple disk space alert:

```bash
crontab -e
```

Add:

```cron
# Alert if disk usage > 80%
0 6 * * * df -h / | awk '{if(NF>0 && $5+0 > 80) print "Disk usage alert: " $5}' >> /home/ubuntu/yoyo-Crawler/logs/disk-alerts.log
```

### 11.6 Health Check Monitoring

Simple uptime monitor (add to crontab):

```cron
# Health check every 5 minutes
*/5 * * * * curl -s -f http://127.0.0.1:8000/health/ > /dev/null || echo "$(date) - Health check failed" >> /home/ubuntu/yoyo-Crawler/logs/health-check.log
```

Or use external services:
- [UptimeRobot](https://uptimerobot.com/) (free)
- [Better Uptime](https://betteruptime.com/)
- AWS CloudWatch Alarms

---

## 12. Rollback Plan

**Before switching over completely, keep Lightsail running for 1-2 weeks.**

### 12.1 Quick Rollback to Lightsail

If EC2 has issues, instantly rollback:

1. **Update LINE webhook URL** back to Lightsail:
   ```
   https://bot.yoyo.club.tw/callback/
   ```
   (Point DNS back to Lightsail IP, or use Lightsail's IP directly)

2. **Update DNS A record** to point back to Lightsail IP

3. **Restart Lightsail service:**
   ```bash
   ssh ubuntu@<lightsail-ip>
   cd /home/ubuntu/yoyo-Crawler
   ./deploy.sh
   ```

4. Data is safe because:
   - Lightsail syncs to Gist on every write
   - EC2 syncs to the same Gist
   - When you switch back, Lightsail has all the data

### 12.2 Parallel Running (Testing Period)

During the migration, you can run both in parallel:

1. **Keep Lightsail active** with current webhook
2. **Test EC2** using a different domain:
   ```
   https://bot-test.yoyo.club.tw/callback/
   ```
3. Create a test LINE channel for EC2
4. Once EC2 is stable, switch webhook to EC2

### 12.3 Final Cutover Checklist

Before shutting down Lightsail:

- [ ] EC2 has been running stable for 7+ days
- [ ] All cron jobs are firing correctly
- [ ] LINE webhook verification passes
- [ ] Users can interact with bot normally
- [ ] Food logging, image recognition, and reports work
- [ ] Rich Menu works
- [ ] LIFF editor loads
- [ ] SSL working via Cloudflare (Origin Certificate, 15-year validity)
- [ ] Logs show no critical errors
- [ ] Database is syncing to Gist
- [ ] Backup plan is in place

### 12.4 Lightsail Shutdown

Once EC2 is proven stable:

1. **Stop Lightsail instance** (don't delete yet):
   - AWS Console → Lightsail → Your instance → **Stop**
   - This pauses billing but keeps the instance for emergency

2. **Wait 2 more weeks**

3. **Delete Lightsail instance**:
   - Lightsail Console → Your instance → **Delete**
   - Also delete the attached static IP if not needed

4. **Delete Lightsail snapshots** (if any):
   - Lightsail → Snapshots → Delete old snapshots

---

## Summary Checklist

### Pre-Migration
- [x] Backed up `.env` file
- [x] Verified Gist has latest data
- [x] Noted current webhook URL

### EC2 Setup
- [x] Launched t2.medium Ubuntu 22.04
- [x] Configured security group (22, 80, 443)
- [x] Allocated and associated Elastic IP
- [x] SSH key setup

### Server Provisioning
- [x] System updates
- [x] Installed Python 3.10, pip, venv
- [x] Installed Nginx
- [x] Installed CJK fonts
- [x] Installed Git

### Deployment
- [x] Cloned repository
- [x] Created virtualenv
- [x] Installed requirements
- [x] Created `.env` file
- [x] Ran migrations
- [x] Collected static files
- [x] Restored data from Gist

### Services
- [x] Configured Gunicorn systemd service
- [x] Configured Nginx reverse proxy
- [x] Installed Cloudflare Origin Certificate
- [x] Both services enabled and running

### Configuration
- [x] Enabled IPv6 (VPC, Subnet, Route Table, Instance)
- [x] Updated Cloudflare DNS (A record, proxied)
- [x] Configured Cloudflare WAF skip rule
- [x] Updated LINE webhook URL
- [x] Updated LIFF endpoint URL
- [x] Set up cron jobs
- [x] Tested deploy script

### Verification
- [x] Health endpoint responds
- [x] SSL working via Cloudflare
- [x] Bot responds to messages
- [x] Data restored correctly
- [x] Logs are clean
- [x] Cron jobs tested

### Monitoring
- [x] Log rotation configured
- [x] Systemd journal limited
- [x] Health check monitoring
- [x] Know how to check logs

### Rollback
- [x] Lightsail still running (kept for 1-2 weeks)
- [x] Know how to rollback if needed

---

## Cost Comparison

| Component | Lightsail | EC2 t2.medium | Notes |
|-----------|-----------|---------------|-------|
| Compute | $3.50/mo | ~$33.87/mo | t2.medium on-demand pricing |
| Storage (20 GB) | Included | ~$1.60/mo | EBS gp3 |
| Static IP | Free | Free (if attached) | |
| Data transfer | 1 TB included | 100 GB free | |
| SSL | Free (Cloudflare) | Free (Cloudflare Origin Cert) | |
| **Total** | **$3.50/mo** | **~$35.50/mo** | |

**Cost Optimization Options:**

1. **Reserved Instance (1 year)**: ~$15/mo (save 55%)
2. **Reserved Instance (3 years)**: ~$10/mo (save 70%)
3. **Savings Plan**: Flexible, ~20-40% savings
4. **Spot Instance**: ~$10/mo, but can be interrupted
5. **Downgrade to t2.small**: ~$17/mo if performance is sufficient

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `systemctl status yoyo-linebot` shows failed | Check logs: `sudo journalctl -u yoyo-linebot -n 50` |
| 502 Bad Gateway | Gunicorn not running or crashed. Restart: `sudo systemctl restart yoyo-linebot` |
| 504 Gateway Timeout | Increase Nginx timeouts in config (`proxy_read_timeout`) |
| LINE webhook verify fails | Check DNS, SSL, ALLOWED_HOSTS, security group rules |
| Cloudflare 521 error | Nginx not listening on IPv6 — ensure `listen [::]:443 ssl;` is in config |
| Cloudflare 522 error | Server unreachable — check security group has 443 open on both IPv4 & IPv6 |
| Cloudflare 403 error | WAF blocking request — check Security → WAF skip rule for `/callback/` |
| Database empty after migration | Run: `python manage.py setup_gist --load` |
| Cron jobs not firing | Check crontab: `crontab -l`, check logs in `/home/ubuntu/yoyo-Crawler/logs/` |
| Out of disk space | Check: `df -h`, clean logs: `sudo journalctl --vacuum-size=100M` |
| High memory usage | Reduce Gunicorn workers or upgrade to t2.large |
| Can't SSH | Check security group allows port 22 from your IP |

---

## Next Steps

After successful migration:

1. **Monitor for 1-2 weeks** before shutting down Lightsail
2. **Set up CloudWatch alarms** for CPU, memory, disk (optional)
3. **Configure automated backups** (Gist already handles this)
4. **Document any customizations** you make
5. **Consider Reserved Instance** if staying on EC2 long-term

---

## Additional Resources

- [Django Deployment Checklist](https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/)
- [Gunicorn Settings](https://docs.gunicorn.org/en/stable/settings.html)
- [Nginx Pitfalls](https://www.nginx.com/resources/wiki/start/topics/tutorials/config_pitfalls/)
- [Cloudflare Origin Certificates](https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/)
- [AWS EC2 Best Practices](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-best-practices.html)

---

**Migration Guide Version:** 1.0
**Last Updated:** 2026-03-30
**Target Platform:** AWS EC2 Ubuntu 22.04 LTS, t2.medium
