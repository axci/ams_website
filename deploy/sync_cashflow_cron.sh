#!/bin/sh
# Scheduled cash-flow sync. Fetches cash-flow documents from the 1C (УНФ) HTTP
# service and loads them into the PRODUCTION database (reports.CashflowDocument)
# for the admin report (Отчёты → Денежный поток).
#
# Like deploy/sync_erp_cron.sh this must run on a machine on the office LAN (the
# one that can reach the 1C service); the cloud cannot. It reuses the SAME
# per-schedule config as the ERP sync — deploy/sync_erp.env (gitignored) — for
# the SSH tunnel to the VPS Postgres, DATABASE_URL (pointed at the tunnel), and
# the 1C credentials (CASHFLOW_1C falls back to ERP_USER/ERP_PASSWORD). The 1C
# URL (CASHFLOW_1C_URL) is read from .env by Django.
#
# Schedule it a little OFF the ERP sync times (it opens a tunnel on the same
# local port), e.g. 09:30 / 15:30 via launchd (ru.asibir.synccashflow) or cron.
#
# Leave ERP_DB_TUNNEL unset (or 0) in sync_erp.env to sync the LOCAL database.

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1

# Reuse the ERP sync's config (production DATABASE_URL, 1C creds, tunnel).
[ -f "$PROJECT_DIR/deploy/sync_erp.env" ] && . "$PROJECT_DIR/deploy/sync_erp.env"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/sync_cashflow.log"

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
    TUNNEL_CTL="$(mktemp -u "${TMPDIR:-/tmp}/cashflow_tunnel.XXXXXX")"
    KEY_OPT=""
    [ -n "${ERP_SSH_KEY:-}" ] && KEY_OPT="-o IdentitiesOnly=yes -i ${ERP_SSH_KEY}"
    if ssh -M -S "$TUNNEL_CTL" -f -N $KEY_OPT \
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

"$PROJECT_DIR/venv/bin/python" manage.py sync_cashflow "$@" >> "$LOG" 2>&1
status=$?
echo "===== $(stamp) end (sync_cashflow=$status) =====" >> "$LOG"
exit $status
