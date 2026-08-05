# Production deployment (Timeweb VPS)

The site runs on a single Timeweb Cloud Server in Russia as an all-in-one Docker
Compose stack. Migrated off Render in 2026-07 (Render's US IPs were SNI-filtered
from Russia).

## Architecture

- **VPS:** `root@201.24.115.147`, Ubuntu 24.04, repo cloned at `/opt/ams`.
- **Stack** (`deploy/compose.prod.yml`) — three containers:
  - `db` — Postgres 18 (named volume `pgdata` mounted at `/var/lib/postgresql`).
  - `web` — this app (gunicorn + WhiteNoise). The entrypoint runs
    `migrate` + `collectstatic` on every start.
  - `caddy` — automatic Let's Encrypt TLS, reverse-proxies to `web:8000`, and
    serves user media from disk.
- **Media:** local disk `/opt/ams/media` (bind-mounted into web at `/app/media`,
  into Caddy at `/srv/media`). Django uses FileSystemStorage — no object storage.
- **Config:** `/opt/ams/deploy/.env.prod` (gitignored — never commit).
  Template: `deploy/.env.prod.example`.

## Deploy a change

Pushing to `main` does **not** auto-deploy — deployment is manual:

```sh
ssh -o ServerAliveInterval=30 root@201.24.115.147   # sessions drop on idle
cd /opt/ams && git pull
docker compose -f deploy/compose.prod.yml up -d --build web   # code change
# Caddyfile change instead:
docker compose -f deploy/compose.prod.yml restart caddy
```

Migrations run automatically in the web entrypoint. Docker Hub is rate-limited
from the VPS, so a registry mirror is configured in `/etc/docker/daemon.json`.

## 1C (УНФ) sync

Prices/stock (`sync_erp`) and company debt (`sync_debts`) come from a 1C service
on the **office LAN** (e.g. `http://192.168.0.10/...`). The VPS can't reach that
LAN, so the sync runs from an office machine and writes into the production DB.

The production Postgres is bound to the **VPS loopback only** (`127.0.0.1:5432`
in `compose.prod.yml`) — not internet-exposed — so the office machine reaches it
over an **SSH tunnel**. `deploy/sync_erp_cron.sh` opens the tunnel, runs both
commands, and closes it. Configure it via `deploy/sync_erp.env` (gitignored):

```sh
export ERP_DB_TUNNEL=1
export ERP_SSH_HOST="root@201.24.115.147"
export ERP_TUNNEL_LOCAL_PORT=15432
export ERP_TUNNEL_REMOTE_HOSTPORT="127.0.0.1:5432"
export DATABASE_URL="postgresql://ams:<POSTGRES_PASSWORD>@127.0.0.1:15432/ams?connect_timeout=10"
export DB_SSL_REQUIRE=false   # the SSH tunnel already encrypts the link
# plus ERP_PRODUCTS_URL / ERP_DEBTS_URL / ERP_USER / ERP_PASSWORD
```

Requirements: the office machine needs passwordless (key-based, `BatchMode`) SSH
to `ERP_SSH_HOST`, and the VPS must expose the loopback port (redeploy `db` after
adding the `ports:` mapping). Schedule the script, e.g.:

```sh
0 8,10,12,14,16 * * * /path/to/ams_website/deploy/sync_erp_cron.sh
```

Logs go to `logs/sync_erp.log`. Test once by hand with `--dry-run` (writes
nothing) to confirm the tunnel + credentials before relying on the schedule.

## Notes

- **TLS:** Caddy obtains and renews the certificate automatically; it needs
  ports 80 + 443 open and DNS pointing at the VPS.
- **Email:** SMTP via Gmail. Timeweb blocks outbound SMTP (25/465/587) by
  default — the ports were unblocked via a support ticket. On a host that won't
  unblock them, switch to an HTTP email API (django-anymail Brevo/Resend over
  443; `EMAIL_BACKEND=anymail.backends.brevo.EmailBackend` + `BREVO_API_KEY`).
- **`.env.prod` and docker compose:** compose interpolates the env file, so a
  literal `$` in a secret value must be doubled to `$$`.
- **Backups:** run a nightly `pg_dump` of the `db` container — it holds the only
  copy of order/customer data now that Render's managed backups are gone.
