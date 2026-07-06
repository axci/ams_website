#!/bin/sh
# Scheduled 1C (УНФ) -> catalog sync. Runs `manage.py sync_erp` and appends a
# timestamped log. Must run on a machine on the office LAN (the one that can
# reach the 1C service); the cloud cannot.
#
# Schedule it at 08/10/12/14/16 every day, e.g. via crontab:
#   0 8,10,12,14,16 * * * /full/path/to/deploy/sync_erp_cron.sh
#
# By default it updates the LOCAL database. To update PRODUCTION, put the Render
# external database URL in deploy/sync_erp.env (gitignored):
#   export DATABASE_URL="postgres://USER:PASSWORD@HOST:5432/DBNAME"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

# Optional per-schedule environment (e.g. production DATABASE_URL). Not committed.
[ -f "$PROJECT_DIR/deploy/sync_erp.env" ] && . "$PROJECT_DIR/deploy/sync_erp.env"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/sync_erp.log"

echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') start =====" >> "$LOG"
"$PROJECT_DIR/venv/bin/python" manage.py sync_erp "$@" >> "$LOG" 2>&1
status=$?
echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') end (exit $status) =====" >> "$LOG"
exit $status
