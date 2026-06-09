#!/bin/sh
set -e

echo "Waiting for the database..."
python - <<'PYEOF'
import os, time, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ams.settings")
django.setup()
from django.db import connections
from django.db.utils import OperationalError
for _ in range(60):
    try:
        connections["default"].ensure_connection()
        break
    except OperationalError:
        time.sleep(1)
else:
    raise SystemExit("Database not reachable after 60s")
print("Database is up.")
PYEOF

echo "Applying migrations..."
python manage.py migrate --noinput

case "$(printf '%s' "${SEED_DEMO:-}" | tr '[:upper:]' '[:lower:]')" in
  1 | true | yes | on)
    echo "Seeding demo content..."
    python manage.py bootstrap_demo
    ;;
esac

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting gunicorn on port ${PORT:-8000}..."
exec gunicorn ams.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-3}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --access-logfile - --error-logfile -
