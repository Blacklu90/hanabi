#!/usr/bin/env bash
# Copy Hanabi's code and data into the Android project before building the APK:
#   app/                         -> android/app/src/main/python/app   (Python code, run by Chaquopy)
#   templates/ static/ data/...  -> android/app/src/main/assets/hanabi (copied to app storage on first start)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f data/content.db ] || { echo "data/content.db is missing — build it first (see README)."; exit 1; }
PY=android/app/src/main/python/app
AS=android/app/src/main/assets/hanabi
mkdir -p "$PY" "$AS/data"
cp -a app/. "$PY/"
find "$PY" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -f "$PY/desktop.py"   # the desktop launcher isn't used on Android
cp -a templates static "$AS/"
cp -a data/content.db data/content_report.json data/strokes "$AS/data/"
echo "Staged Hanabi for Android ($(du -sh "$AS" | cut -f1) of assets)."
