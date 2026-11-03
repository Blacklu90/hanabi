#!/usr/bin/env bash
# Hanabi installer for Linux: run once, then start Hanabi from your app menu.
#   ./install.sh            install / update
#   ./install.sh --remove   remove the app (asks before deleting your progress)
set -e
APP="$HOME/.local/share/hanabi"
BIN="$HOME/.local/bin"
DESK="$HOME/.local/share/applications"
SRC="$(cd "$(dirname "$0")" && pwd)"

if [ "$1" = "--remove" ]; then
  "$BIN/hanabi" stop 2>/dev/null || true
  rm -f "$BIN/hanabi" "$DESK/hanabi.desktop" "$HOME/Desktop/hanabi.desktop"
  read -r -p "Also delete your Hanabi progress and account data in $APP? [y/N] " a
  if [ "$a" = "y" ] || [ "$a" = "Y" ]; then rm -rf "$APP"; echo "Removed everything."; else echo "App removed. Your data is still in $APP"; fi
  exit 0
fi

if ! command -v python3 >/dev/null; then
  echo "Python 3 is needed. On Arch run:  sudo pacman -S python"
  exit 1
fi

[ -x "$BIN/hanabi" ] && "$BIN/hanabi" stop >/dev/null 2>&1 || true  # restart on the new version
echo "→ Installing Hanabi to $APP"
mkdir -p "$APP" "$BIN" "$DESK"
# Copy the app, but never overwrite an existing database (that's your progress).
if [ -f "$APP/data/hanabi.db" ]; then
  echo "→ Keeping your existing progress"
  cp "$APP/data/hanabi.db" "$APP/data/hanabi.db.before-update"
  tar -C "$SRC" --exclude=.venv --exclude=data/hanabi.db --exclude='data/hanabi.db-*' -cf - . | tar -C "$APP" -xf -
else
  tar -C "$SRC" --exclude=.venv -cf - . | tar -C "$APP" -xf -
fi

if [ ! -x "$APP/.venv/bin/uvicorn" ]; then
  echo "→ Setting up Python packages (one time, ~30 s)"
  python3 -m venv "$APP/.venv"
  "$APP/.venv/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"
fi
"$APP/.venv/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"  # picks up new versions on update

# A fresh git clone has no content.db (it's generated): build it from the original dictionaries once.
if [ ! -f "$APP/data/content.db" ]; then
  echo "→ Building the kanji/dictionary database from KANJIDIC2, JMdict and Tatoeba (one time, ~1 minute, ~160 MB download)"
  (cd "$APP" && ./scripts/fetch_sources.sh && .venv/bin/python -m scripts.build_content >/dev/null)
fi

# Sound was removed from Hanabi: clean up files and the ~350 MB voice package left by older versions.
rm -rf "$APP/data/tts_cache"
rm -f "$APP/app/tts.py" "$APP/requirements-voice.txt" "$APP/tests/test_tts.py"
if "$APP/.venv/bin/python" -c "import pyopenjtalk" >/dev/null 2>&1; then
  echo "→ Removing the old voice package"
  "$APP/.venv/bin/pip" uninstall -y -q pyopenjtalk-plus sudachidict_core sudachipy 2>/dev/null || true
fi

cat > "$BIN/hanabi" <<EOF
#!/usr/bin/env bash
# hanabi        start (if needed) and open in the browser
# hanabi stop   stop the background server
APP="$APP"; URL="http://127.0.0.1:8000"; PIDF="\$APP/hanabi.pid"
running() { [ -f "\$PIDF" ] && kill -0 "\$(cat "\$PIDF")" 2>/dev/null; }
if [ "\$1" = "stop" ]; then
  running && kill "\$(cat "\$PIDF")" && echo "Hanabi stopped."; rm -f "\$PIDF"; exit 0
fi
if ! running; then
  cd "\$APP"
  nohup "\$APP/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 --log-level warning > "\$APP/hanabi.log" 2>&1 &
  echo \$! > "\$PIDF"
  for i in \$(seq 1 150); do curl -s -o /dev/null "\$URL" && break; sleep 0.2; done  # first start after an update copies new content in
fi
xdg-open "\$URL" >/dev/null 2>&1 &
EOF
chmod +x "$BIN/hanabi"

cat > "$DESK/hanabi.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Hanabi
GenericName=Learn Japanese
Comment=Japanese in short, focused bursts
Exec=$BIN/hanabi
Icon=$APP/static/img/icon.svg
Terminal=false
Categories=Education;Languages;
Actions=stop;

[Desktop Action stop]
Name=Stop Hanabi server
Exec=$BIN/hanabi stop
EOF
chmod +x "$DESK/hanabi.desktop"
if [ -d "$HOME/Desktop" ]; then
  cp "$DESK/hanabi.desktop" "$HOME/Desktop/hanabi.desktop"
  chmod +x "$HOME/Desktop/hanabi.desktop"
  gio set "$HOME/Desktop/hanabi.desktop" metadata::trusted true 2>/dev/null || true
fi
command -v update-desktop-database >/dev/null && update-desktop-database "$DESK" 2>/dev/null || true

echo
echo "✓ Done! Open Hanabi from your app menu (search \"Hanabi\") or the desktop icon."
echo "  Or type:  hanabi        (stop it with: hanabi stop)"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  (To use the 'hanabi' command, add ~/.local/bin to your PATH.)";; esac
"$BIN/hanabi"
