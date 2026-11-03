#!/usr/bin/env sh
# Start Hanabi on http://127.0.0.1:8000  (first run creates .venv and installs dependencies)
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
if [ ! -f data/content.db ]; then
  echo "Building the kanji/dictionary database (one time, ~1 minute, ~160 MB download)…"
  ./scripts/fetch_sources.sh && .venv/bin/python -m scripts.build_content >/dev/null
fi
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
