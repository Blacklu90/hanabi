#!/usr/bin/env bash
# Update Shuinkan (formerly Hanabi) on Linux to the newest release, keeping all your progress.
#
#   shuinkan-update            download the newest AppImage if there is one, then refresh the menu entry
#   shuinkan-update --force    download even if you already have the newest version
#
# The app lives in ~/Applications/Shuinkan.AppImage (the same place `--install` uses).
# Your progress is in ~/.local/share/shuinkan and is never touched by this script.
set -euo pipefail

REPO="${SHUINKAN_REPO:-Blacklu90/hanabi}"
API="${SHUINKAN_RELEASE_API:-https://api.github.com/repos/$REPO/releases/latest}"
DIR="${SHUINKAN_APP_DIR:-$HOME/Applications}"
APP="$DIR/Shuinkan.AppImage"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# Run the AppImage; if FUSE is missing (Arch: the fuse2 package), fall back to extract-and-run.
run_app() {
  "$APP" "$@" 2>/dev/null || APPIMAGE_EXTRACT_AND_RUN=1 "$APP" "$@"
}

command -v curl >/dev/null || fail "curl is needed:  sudo pacman -S curl"

say "Looking for the newest Shuinkan…"
json=$(curl -fsSL -H "Accept: application/vnd.github+json" "$API") || fail "Couldn't reach GitHub. Are you online?"
tag=$(printf '%s' "$json" | grep -o '"tag_name": *"[^"]*"' | head -n1 | sed 's/.*"\([^"]*\)"$/\1/')
url=$(printf '%s' "$json" | grep -o '"browser_download_url": *"[^"]*x86_64\.AppImage"' | head -n1 | sed 's/.*"\(http[^"]*\)"$/\1/')
[ -n "$tag" ] && [ -n "$url" ] || fail "The newest release has no Linux AppImage yet. Try again later."
latest="${tag#v}"

current=""
if [ -x "$APP" ]; then
  current=$(run_app --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true)
fi
if [ "$current" = "$latest" ] && [ $FORCE = 0 ]; then
  say "Shuinkan $current is already the newest version. ✓"
  run_app --install-voice 2>/dev/null | grep -v "already installed" || true  # make sure the voice is there
  exit 0
fi
say "Updating Shuinkan ${current:-(not installed yet)} → $latest"

mkdir -p "$DIR"
tmp="$APP.download"
trap 'rm -f "$tmp"' EXIT
curl -fL --progress-bar -o "$tmp" "$url" || fail "Download failed. Nothing was changed."
# Make sure we got a program, not an error page.
[ "$(head -c 4 "$tmp" | od -An -tx1 | tr -d ' \n')" = "7f454c46" ] || fail "The download isn't a Linux program. Nothing was changed."
chmod +x "$tmp"

# Stop a running copy (it closes by itself otherwise after 2 hours).
if [ -x "$APP" ]; then run_app --stop >/dev/null 2>&1 || true; fi
# Older installs made with install.sh had their own launcher: stop it, and remove its menu entry so there's only one.
for old in "$HOME/.local/bin/shuinkan" "$HOME/.local/bin/hanabi"; do
  if [ -f "$old" ] && grep -q "uvicorn" "$old" 2>/dev/null; then
    "$old" stop >/dev/null 2>&1 || true
    rm -f "$old"
    say "Removed the old launcher $old (your progress is kept)."
  fi
done
for old in "$HOME/.local/share/applications/hanabi.desktop" "$HOME/Desktop/hanabi.desktop"; do
  if [ -f "$old" ] && grep -qi "hanabi" "$old"; then rm -f "$old"; fi
done

mv -f "$tmp" "$APP"
trap - EXIT
# Menu entry + icon point to the new file; also sets up the built-in Japanese voice the first time (kept across updates).
run_app --install || echo "(The voice can be installed later from Settings → Voice.)"

say "Done! Shuinkan $latest is installed. ✓"
echo "Start it from your app menu, or run: $APP"
if ! "$APP" --version >/dev/null 2>&1; then
  echo "Tip: install FUSE so the app starts faster:  sudo pacman -S fuse2"
fi
