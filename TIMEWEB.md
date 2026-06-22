# Deploying on Timeweb Cloud — App Platform

Timeweb Cloud builds this repo's **Dockerfile** and runs it as one app, with a
managed **PostgreSQL** database and automatic HTTPS. Static files are served by
**WhiteNoise**; uploaded media should sit on a persistent disk mounted at
`/app/media`.

> Unlike Render/Railway, Timeweb's domain is **not** auto-detected, so you set
> `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` yourself (Step 4). Menu names in the
> Timeweb panel may differ slightly from the labels below — map them to the same
> ideas (build from Dockerfile, env vars, port, managed Postgres).

## 1. Push the repo
Timeweb builds from Git, so push first (GitHub/GitLab):

```bash
git add -A && git commit -m "Deploy config" && git push
```

## 2. Create a managed PostgreSQL
Timeweb Cloud → **Базы данных (Databases) → PostgreSQL** → create (same region as
the app). Copy its **host, port, user, password, database name**, and assemble:

```
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
```

## 3. Create the App
Timeweb Cloud → **Приложения (Apps) → Create → from GitHub/GitLab**, select this
repo. Build type: **Dockerfile** (auto-detected).
- **Port:** `8000` — gunicorn binds `0.0.0.0:8000` by default. (If Timeweb injects
  a `PORT` variable, the entrypoint honors it automatically.)
- **No run command** — the Dockerfile `ENTRYPOINT` runs migrate → seed →
  collectstatic → gunicorn.

## 4. Environment variables

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql://USER:PASSWORD@HOST:PORT/DBNAME` (Step 2) |
| `DB_SSL_REQUIRE` | `true` (managed PG over a public host needs SSL) |
| `SECRET_KEY` | long random (`python -c "import secrets; print(secrets.token_urlsafe(50))"`) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | your app domain, e.g. `myapp-xxxx.twc1.net` |
| `CSRF_TRUSTED_ORIGINS` | `https://myapp-xxxx.twc1.net` (must match, with `https://`) |
| `SEED_DEMO` | `true` (loads demo catalog + `admin`/`buyer` logins) |
| `EMAIL_HOST` | `smtp.gmail.com` |
| `EMAIL_PORT` | `465` |
| `EMAIL_USE_SSL` | `true` |
| `EMAIL_USE_TLS` | `false` |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `DEFAULT_FROM_EMAIL` | Gmail + 16-char app password |

You won't know the domain until the app exists — **deploy once, copy the
generated domain, then set `ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS` and redeploy.**
After seeding, log in with `admin` / `demo12345` and `buyer` / `demo12345`
(override via `DEMO_ADMIN_PASSWORD` / `DEMO_BUYER_PASSWORD`).

## 5. Persistent media (recommended)
Attach a disk/volume mounted at **`/app/media`** so uploaded product/banner images
survive redeploys. (`SEED_DEMO` re-copies the demo images each deploy, but your own
uploads would be lost without a disk.)

## 6. Email
Timeweb (a Russian host) can reach both Gmail and **Yandex**, so you can also send
from your own domain: `EMAIL_HOST=smtp.yandex.ru`, `EMAIL_HOST_USER=fd@automech.su`
+ a Yandex app password. If a deploy logs `Network is unreachable` on the SMTP port,
switch to the HTTP API: `EMAIL_BACKEND=anymail.backends.brevo.EmailBackend` +
`BREVO_API_KEY=...` (works over port 443).
