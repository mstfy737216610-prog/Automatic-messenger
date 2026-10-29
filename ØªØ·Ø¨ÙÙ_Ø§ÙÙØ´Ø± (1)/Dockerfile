FROM node:20-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY tailwind.config.js postcss.config.js components.json eslint.config.js ./
COPY src ./src
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    CHROMIUM_PATH=/usr/bin/chromium \
    PLAYWRIGHT_BROWSERS_PATH=0 \
    DRY_RUN=true \
    PUBLISHING_ENABLED=false
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium ffmpeg tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY automation ./automation
COPY assets ./assets
COPY config ./config
COPY proxies.txt .env.example ./
COPY --from=frontend /build/dist ./dist
RUN mkdir -p /app/data && chmod 700 /app/data
EXPOSE 8000
VOLUME ["/app/data"]
CMD ["python", "-m", "automation", "serve"]
