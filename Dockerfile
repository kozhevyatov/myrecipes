# ---------- 1. Сборка фронтенда ----------
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

# ---------- 2. Бэкенд + статика ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    PORT=1331

WORKDIR /app
# Распознавание текста со скриншотов рецептов (русский + английский)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus \
 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /src/dist ./static

VOLUME /data
EXPOSE 1331

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"

# --proxy-headers: корректная схема (https) за reverse proxy Synology
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
