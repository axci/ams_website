# Deploying on Railway

Railway builds this repo's **Dockerfile** and runs it as one web service, with
managed PostgreSQL and automatic HTTPS. No nginx required — static files are
served by **WhiteNoise**, and media by Django (back it with a **Volume**).

## Steps

1. Push this repo to GitHub.
2. **Railway → New Project → Deploy from GitHub repo** (it picks up the Dockerfile / `railway.json`).
3. **Add PostgreSQL:** New → Database → PostgreSQL.
4. Open the **web service → Variables** and set:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference the Postgres service) |
   | `SECRET_KEY` | a long random value (`python -c "import secrets; print(secrets.token_urlsafe(50))"`) |
   | `DEBUG` | `False` |
   | `EMAIL_HOST` | `smtp.yandex.ru` |
   | `EMAIL_PORT` | `465` |
   | `EMAIL_USE_SSL` | `true` |
   | `EMAIL_USE_TLS` | `false` |
   | `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `DEFAULT_FROM_EMAIL` | your Yandex mailbox + app password |

   `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are filled automatically from
   Railway's domain. For HTTPS hardening also add:
   `SECURE_SSL_REDIRECT=true`, `SESSION_COOKIE_SECURE=true`,
   `CSRF_COOKIE_SECURE=true`, `SECURE_HSTS_SECONDS=31536000`.

5. **Add a Volume** to the web service with mount path **`/app/media`** so
   uploaded product images and banners survive redeploys.
6. **Generate a domain:** service → Settings → Networking → Generate Domain
   (or attach a custom domain — add it to `ALLOWED_HOSTS` if so).

Each deploy automatically runs migrations and `collectstatic`, then starts
gunicorn on Railway's `$PORT`.

## First-time data

Using the [Railway CLI](https://docs.railway.com/guides/cli) (`railway link` to the project),
you can run management commands against the live database:

```bash
railway run python manage.py createsuperuser
# import the data dump produced during the Postgres switch:
railway run python manage.py loaddata /path/to/ams_datadump.json
```

**Media:** the Volume starts empty, so re-upload images through the admin, or
move to object storage for scale (see below).

## Scaling media (optional)

Django-served media on a single Volume is fine for a small shop. For higher
traffic or multiple replicas, switch to object storage (S3 / Cloudflare R2) via
`django-storages` — ask and I can wire it up.

## Notes
- The `docker-compose.yml` + nginx setup is for self-hosting/VPS; Railway ignores
  it and uses the Dockerfile directly. Both remain supported.
- Local development and `docker compose` are unaffected by these changes.
