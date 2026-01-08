#!/usr/bin/env bash
# Render build script

set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input

echo "=== Running migrations ==="
python manage.py showmigrations
python manage.py migrate --verbosity 2

echo "=== Checking tables ==="
python -c "
import sqlite3
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()
cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table';\")
print('Tables:', [t[0] for t in cursor.fetchall()])
conn.close()
"

echo "=== Loading articles from Gist ==="
python manage.py setup_gist --load || echo "Gist load skipped (not configured or failed)"
