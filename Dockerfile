FROM python:3.12-slim

WORKDIR /app

# System deps for lightgbm / prophet (cmdstan) and healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl cron \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Register the daily job (7:00 AM container-local time) alongside the API.
RUN echo "0 7 * * * cd /app && /usr/local/bin/python -m automation.daily_run >> /app/logs/cron.log 2>&1" \
    > /etc/cron.d/areca-daily \
    && chmod 0644 /etc/cron.d/areca-daily \
    && crontab /etc/cron.d/areca-daily

EXPOSE 8000

# Entrypoint runs cron in the background and the API in the foreground,
# so the container serves the API to any device while still refreshing daily.
CMD cron && uvicorn api.main:app --host 0.0.0.0 --port 8000
