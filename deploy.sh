#!/usr/bin/env bash
# Pull latest code, rebuild, and restart the service.
# Usage: ./deploy.sh

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
