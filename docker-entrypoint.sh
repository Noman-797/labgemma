#!/bin/sh
set -e

mkdir -p /data

# Seed demo accounts on first boot when requested (safe to re-run)
if [ "${SEED_DEMO:-0}" = "1" ]; then
  echo "Seeding demo accounts…"
  python scripts/seed_demo.py
fi

PORT="${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
