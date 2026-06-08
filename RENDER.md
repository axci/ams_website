# Deploying the demo on Render (free)

One free web service runs the Docker image with **SQLite** and the **baked demo
catalog + photos** — no database add-on, no disk, no object storage. Every start
restores a fully-populated demo.

## Deploy (Blueprint — a few clicks)
1. Commit & push to GitHub (including `deploy/demo_data.json`,
   `deploy/demo_media/`, and `render.yaml`).
2. Render Dashboard → **New → Blueprint** → select this repo. Render reads
   `render.yaml` and creates a **free** Docker web service.
3. **Apply**, wait for the build, then open the `https://<name>.onrender.com` URL.

The container automatically migrates, loads the demo catalog + images, collects
static, and starts gunicorn.

## Demo logins
- **Buyer:** `buyer` / `demo12345` — browse, see stock, add to basket, order.
- **Admin:** `admin` / *(auto-generated)* — find it under the service's
  **Environment → `DEMO_ADMIN_PASSWORD`** in the Render dashboard; log in at `/admin/`.

## Good to know
- **Cold start:** a free service sleeps after ~15 min idle; the next request
  takes ~30–60s to wake. Normal for the free tier.
- **Resets:** the free tier has no persistent disk, so any changes/uploads reset
  on redeploy/restart — and are restored from the baked demo. Ideal for showing
  the site, not for real data.

## Turning it into a real site later
Add a Render **PostgreSQL** instance and set `DATABASE_URL`, set `SEED_DEMO=false`,
and move media to **S3 / Cloudflare R2** (`django-storages`) — or use the
`docker compose` / VPS setup in `DEPLOY.md`.
