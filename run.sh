#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate
python scripts/seed_demo.py
exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
