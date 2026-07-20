# LabGemma — FastAPI + multi-language judge (Python / C / C++ / Java)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DATABASE_URL=sqlite:////data/labgemma.db

WORKDIR /app

# Compilers for the lightweight judge
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc \
      g++ \
      default-jdk-headless \
      curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh \
    && mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
