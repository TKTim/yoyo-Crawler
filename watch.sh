#!/usr/bin/env bash
# Watch for file changes and auto-restart the service.
# Uses inotifywait to monitor Python/HTML/config file changes.
#
# Install: sudo apt install inotify-tools
# Usage:   ./watch.sh
# Stop:    Ctrl+C

set -e

cd "$(dirname "$0")"
source venv/bin/activate

WATCH_DIR="$(pwd)"
WATCH_EXTENSIONS="py,html,txt,json"
DEBOUNCE=3  # seconds to wait before restarting (avoids rapid restarts)

echo "Watching $WATCH_DIR for changes..."
echo "Extensions: $WATCH_EXTENSIONS"
echo "Press Ctrl+C to stop"
echo ""

LAST_RESTART=0

inotifywait -m -r \
    --include '.*\.(py|html|txt|json)$' \
    --exclude '(\.git|venv|__pycache__|staticfiles|db\.sqlite3)' \
    -e modify,create,delete \
    "$WATCH_DIR" |
while read -r directory event filename; do
    NOW=$(date +%s)
    DIFF=$((NOW - LAST_RESTART))

    if [ "$DIFF" -lt "$DEBOUNCE" ]; then
        continue
    fi

    LAST_RESTART=$NOW
    echo ""
    echo "[$(date '+%H:%M:%S')] Change detected: $filename ($event)"
    echo "[$(date '+%H:%M:%S')] Restarting service..."

    python manage.py migrate --verbosity 0 2>/dev/null || true
    python manage.py collectstatic --no-input --clear --verbosity 0 2>/dev/null || true
    sudo systemctl restart yoyo-linebot

    echo "[$(date '+%H:%M:%S')] Service restarted"
done
