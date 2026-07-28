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
