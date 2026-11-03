#!/usr/bin/env bash
# Build dist/Shuinkan-x86_64.AppImage: one file that runs on most Linux distributions.
# Needs: bash, curl, a Python 3 to bootstrap `uv` (if not installed), and data/content.db
# (build it with scripts/fetch_sources.sh + python -m scripts.build_content, or download it from a release).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' app/desktop.py)
BUILD=$ROOT/build/appimage
APPDIR=$BUILD/Shuinkan.AppDir
OUT=$ROOT/dist/Shuinkan-$VERSION-x86_64.AppImage
PYVER=${PYVER:-3.12}

[ -f data/content.db ] || { echo "data/content.db is missing — build it first (see README)."; exit 1; }
rm -rf "$APPDIR" && mkdir -p "$APPDIR/usr" "$BUILD/tools" dist

# 1. tools: uv (portable Python downloads) and appimagetool
UV=$(command -v uv || true)
if [ -z "$UV" ]; then
  python3 -m venv "$BUILD/tools/uvenv" && "$BUILD/tools/uvenv/bin/pip" -q install uv
  UV=$BUILD/tools/uvenv/bin/uv
fi
TOOL=$BUILD/tools/appimagetool
if [ ! -x "$TOOL" ]; then
  curl -fL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi

# 2. a relocatable Python (python-build-standalone, via uv)
"$UV" python install "$PYVER" --install-dir "$BUILD/py" >/dev/null
PYSRC=$(find "$BUILD/py" -maxdepth 1 -type d -name "cpython-$PYVER.*-linux-x86_64-gnu" | sort -V | tail -1)
cp -a "$PYSRC" "$APPDIR/usr/python"
PY=$APPDIR/usr/python/bin/python3
LIB=$(echo "$APPDIR"/usr/python/lib/python3.*)
rm -rf "$LIB"/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3,pydoc_data} "$LIB"/config-* \
       "$APPDIR"/usr/python/{include,share} "$APPDIR"/usr/python/lib/{tcl*,tk*,itcl*,thread*} 2>/dev/null || true

# 3. dependencies
"$UV" pip install --quiet --python "$PY" --break-system-packages -r requirements.txt

# 4. Shuinkan itself
DEST=$APPDIR/usr/share/shuinkan
mkdir -p "$DEST/data"
cp -a app templates static packaging README.md DATA_SOURCES.md "$DEST/"
cp -a data/content.db data/strokes data/content_report.json "$DEST/data/"
find "$DEST" "$APPDIR/usr/python" -name __pycache__ -type d -prune -exec rm -rf {} +
"$PY" -m compileall -q -j 0 "$DEST/app" "$LIB" >/dev/null || true   # read-only at runtime, so precompile

# 5. AppImage metadata
cp packaging/shuinkan.desktop "$APPDIR/shuinkan.desktop"
cp packaging/shuinkan.png "$APPDIR/shuinkan.png"
cp packaging/shuinkan.png "$APPDIR/.DirIcon"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME PYTHONPATH
exec "$HERE/usr/python/bin/python3" "$HERE/usr/share/shuinkan/app/desktop.py" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# 6. pack (works without FUSE, e.g. in CI)
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream "$APPDIR" "$OUT" >/dev/null
ln -sf "$(basename "$OUT")" dist/Shuinkan-x86_64.AppImage
echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
