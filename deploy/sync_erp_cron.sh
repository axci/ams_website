#!/bin/sh
# Scheduled 1C (УНФ) sync. Runs the product sync (sync_erp) and the debt sync
# (sync_debts) and appends a timestamped log. Must run on a machine on the
# office LAN (the one that can reach the 1C service); the cloud cannot.
#
# Schedule it at 08/10/12/14/16 every day, e.g. via crontab:
#   0 8,10,12,14,16 * * * /full/path/to/deploy/sync_erp_cron.sh
#
# The production database now lives INSIDE the Timeweb VPS Docker stack and is
# bound to the VPS loopback only (deploy/compose.prod.yml) — it is not reachable
# over the internet. So when ERP_DB_TUNNEL=1 this script first opens an SSH
# tunnel to it, then points Django at the local end via DATABASE_URL.
#
# Per-schedule config/secrets live in deploy/sync_erp.env (gitignored), e.g.:
#   export ERP_PRODUCTS_URL=... ERP_DEBTS_URL=... ERP_USER=... ERP_PASSWORD=...
#   export ERP_DB_TUNNEL=1
#   export ERP_SSH_HOST="root@201.24.115.147"
#   export ERP_TUNNEL_LOCAL_PORT=15432
#   export ERP_TUNNEL_REMOTE_HOSTPORT="127.0.0.1:5432"
#   export DATABASE_URL="postgresql://ams:PASSWORD@127.0.0.1:15432/ams?connect_timeout=10"
#   export DB_SSL_REQUIRE=false   # the SSH tunnel provides the encryption
#
# Leave ERP_DB_TUNNEL unset (or 0) to sync the LOCAL database instead.

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

# Optional per-schedule environment (production DATABASE_URL, ERP creds, tunnel).
[ -f "$PROJECT_DIR/deploy/sync_erp.env" ] && . "$PROJECT_DIR/deploy/sync_erp.env"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/sync_erp.log"

stamp() { date '+%Y-%m-%d %H:%M:%S %z'; }

TUNNEL_CTL=""
cleanup() {
    if [ -n "$TUNNEL_CTL" ]; then
        ssh -S "$TUNNEL_CTL" -O exit "${ERP_SSH_HOST:-}" 2>/dev/null
        TUNNEL_CTL=""
    fi
}
trap cleanup EXIT INT TERM

echo "===== $(stamp) start =====" >> "$LOG"

# Open the SSH tunnel to the VPS Postgres (loopback -> container) if requested.
if [ "${ERP_DB_TUNNEL:-0}" = "1" ]; then
    if [ -z "${ERP_SSH_HOST:-}" ]; then
        echo "$(stamp) ERROR: ERP_DB_TUNNEL=1 but ERP_SSH_HOST is not set" >> "$LOG"
        echo "===== $(stamp) end (tunnel misconfigured) =====" >> "$LOG"
        exit 1
    fi
    LP="${ERP_TUNNEL_LOCAL_PORT:-15432}"
    RH="${ERP_TUNNEL_REMOTE_HOSTPORT:-127.0.0.1:5432}"
    TUNNEL_CTL="$(mktemp -u "${TMPDIR:-/tmp}/erp_tunnel.XXXXXX")"
    if ssh -M -S "$TUNNEL_CTL" -f -N \
            -o BatchMode=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=15 \
            -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
            -L "127.0.0.1:${LP}:${RH}" "$ERP_SSH_HOST" >> "$LOG" 2>&1; then
        echo "$(stamp) SSH tunnel up: 127.0.0.1:${LP} -> ${RH} via ${ERP_SSH_HOST}" >> "$LOG"
    else
        TUNNEL_CTL=""
        echo "$(stamp) ERROR: could not open SSH tunnel to ${ERP_SSH_HOST}" >> "$LOG"
        echo "===== $(stamp) end (tunnel failed) =====" >> "$LOG"
        exit 1
    fi
fi

"$PROJECT_DIR/venv/bin/python" manage.py sync_erp "$@" >> "$LOG" 2>&1
erp=$?
"$PROJECT_DIR/venv/bin/python" manage.py sync_debts "$@" >> "$LOG" 2>&1
debts=$?
status=$erp
[ "$debts" -ne 0 ] && status=$debts
echo "===== $(stamp) end (sync_erp=$erp sync_debts=$debts) =====" >> "$LOG"
exit $status
