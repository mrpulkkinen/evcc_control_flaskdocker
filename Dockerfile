FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5080

# IMPORTANT: use a single worker so the cooldown (in-memory) stays consistent
CMD ["gunicorn", "-b", "0.0.0.0:5080", "app:app", "--workers", "1", "--threads", "8", "--timeout", "60"]
