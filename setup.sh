#!/usr/bin/env bash
# Setup script for deploying yoyo-English on a new server (Lightsail/EC2)
# Usage: ./setup.sh

set -e

echo "========================================="
echo "  YoYo English Bot - Server Setup"
echo "========================================="

# --- Check .env ---
if [ ! -f .env ]; then
    echo ""
    echo "[ERROR] .env file not found."
    echo ""
    echo "Create one first:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    echo ""
    echo "Required variables:"
    echo "  LINE_CHANNEL_ACCESS_TOKEN"
    echo "  LINE_CHANNEL_SECRET"
    echo "  CRON_SECRET"
    echo "  GEMINI_API_KEY"
    echo "  DJANGO_SECRET_KEY"
    echo "  GITHUB_GIST_TOKEN"
    echo "  GIST_ID"
    echo "  ALLOWED_HOSTS"
    exit 1
fi

echo "[1/6] Creating virtual environment..."
if [ ! -d venv ]; then
    python3 -m venv venv
    echo "  Created venv"
else
    echo "  venv already exists, skipping"
fi

source venv/bin/activate

echo "[2/6] Installing dependencies..."
pip install -r requirements.txt --quiet

echo "[3/6] Running migrations..."
python manage.py migrate

echo "[4/6] Collecting static files..."
python manage.py collectstatic --no-input --clear --verbosity 0

echo "[5/6] Loading data from Gist..."
python manage.py setup_gist --load || echo "  Gist load skipped (not configured or failed)"

echo "[6/6] Testing server..."
timeout 3 python manage.py runserver 0.0.0.0:8000 > /dev/null 2>&1 &
SERVER_PID=$!
sleep 2

if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health/ | grep -q "200"; then
    echo "  Health check passed"
else
    echo "  [WARNING] Health check failed — check .env and logs"
fi

kill $SERVER_PID 2>/dev/null || true

echo ""
echo "========================================="
echo "  Setup complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "  1. Set up systemd service:"
echo "     sudo cp yoyo-linebot.service /etc/systemd/system/"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable --now yoyo-linebot"
echo ""
echo "  2. Set up Nginx:"
echo "     sudo cp nginx-yoyo-linebot.conf /etc/nginx/sites-available/yoyo-linebot"
echo "     sudo ln -sf /etc/nginx/sites-available/yoyo-linebot /etc/nginx/sites-enabled/"
echo "     sudo rm -f /etc/nginx/sites-enabled/default"
echo "     sudo nginx -t && sudo systemctl restart nginx"
echo ""
echo "  3. Set up cron jobs:"
echo "     crontab -e"
echo "     # Add:"
echo "     # 0 0 * * * curl -s -X POST http://127.0.0.1:8000/cron/<CRON_SECRET>/"
echo "     # 0 14 * * * curl -s -X POST http://127.0.0.1:8000/dietary-report/<CRON_SECRET>/"
echo ""
echo "  4. Update LINE webhook URL to:"
echo "     https://bot.yoyo.club.tw/callback/"
echo ""
