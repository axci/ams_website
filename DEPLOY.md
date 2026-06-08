# Deploying with Docker

Three containers, orchestrated by Docker Compose:

| Service | Role |
|---------|------|
| **db**   | PostgreSQL 16 (data in the `pgdata` volume) |
| **web**  | Django app served by gunicorn |
| **nginx**| reverse proxy; serves `/static/` and `/media/`, proxies the rest to `web` |

## 1. Prerequisites
Install Docker Engine + Compose plugin, then check: `docker compose version`.

## 2. Configure
```bash
cp .env.docker.example .env.docker
```
Edit `.env.docker`:
- **SECRET_KEY** — generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- **ALLOWED_HOSTS** / **CSRF_TRUSTED_ORIGINS** — your domain(s)
- **DB_PASSWORD** and **POSTGRES_PASSWORD** — the *same* strong value
- Email (Yandex) credentials
- Keep `DEBUG=False`

## 3. Build & start
```bash
docker compose up -d --build
```
The web container waits for the DB, runs migrations, and collects static automatically. Site: **http://<server>/** (port 80).

## 4. Create an admin user
```bash
docker compose exec web python manage.py createsuperuser
```

## 5. (Optional) Import existing data
```bash
# Export from the machine holding the current data:
python manage.py dumpdata --exclude contenttypes --exclude auth.permission \
  --exclude admin.logentry --exclude sessions --indent 2 -o datadump.json
#   (you already have one at /tmp/ams_datadump.json from the Postgres switch)

# Load it into the container DB:
docker compose cp datadump.json web:/tmp/datadump.json
docker compose exec web python manage.py loaddata /tmp/datadump.json

# Copy uploaded images (product pictures, banners) into the media volume:
docker compose cp media/. web:/app/media/
```

## 6. Enable HTTPS
Terminate TLS in front of nginx (Caddy/Traefik, or host nginx + certbot). Then in `.env.docker`:
```
SECURE_SSL_REDIRECT=true
SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
SECURE_HSTS_SECONDS=31536000
```
and re-run `docker compose up -d`.

## Everyday commands
```bash
docker compose logs -f web     # application logs
docker compose exec web sh     # shell inside the app container
docker compose restart web     # restart the app
docker compose down            # stop (keeps data volumes)
docker compose down -v         # stop and DELETE all data (careful!)
```

## Database backup / restore
```bash
docker compose exec db pg_dump -U ams_user ams > backup.sql
cat backup.sql | docker compose exec -T db psql -U ams_user -d ams
```
