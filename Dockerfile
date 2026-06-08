# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the project.
COPY . .

# Create an unprivileged user and the runtime dirs. Named volumes mounted at
# these paths inherit this ownership on first initialisation, so the app user
# can write uploads/collected static.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/media /app/staticfiles \
    && chown -R app:app /app \
    && chmod +x deploy/entrypoint.sh

USER app

EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
