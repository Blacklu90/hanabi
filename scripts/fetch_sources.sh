#!/usr/bin/env sh
# Re-download the original datasets (only needed to rebuild content with scripts/build_content.py).
set -e
cd "$(dirname "$0")/../data/source"
TAG="3.6.2+20261102210542"; T="3.6.2%2B20261102210542"
for f in kanjidic2-en jmdict-eng-common jmdict-examples-eng; do
  curl -fL -o "$f.zip" "https://github.com/scriptin/jmdict-simplified/releases/download/$T/$f-$TAG.json.zip"
  unzip -oq "$f.zip" && rm "$f.zip"
done
# KanjiVG stroke files for the 2,136 kanji and all kana are already in data/strokes/.
echo "Sources ready. Now run: python -m scripts.build_content"
