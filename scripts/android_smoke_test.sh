#!/usr/bin/env bash
# Runs on the CI host while an Android emulator is up: install the APK, start Shuinkan, check it works.
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=android-smoke; mkdir -p "$OUT"
APK=$(ls android/app/build/outputs/apk/release/*.apk | head -1)
echo "Installing $APK ($(du -h "$APK" | cut -f1))"
adb install -r "$APK" || exit 1
adb logcat -c
adb shell am start -n io.github.blacklu90.shuinkan/.MainActivity
ok=0
for i in $(seq 1 100); do      # first start copies the content (about a minute on an emulator)
  adb forward tcp:8765 tcp:8765 >/dev/null 2>&1
  if curl -sf -o /dev/null --max-time 5 http://127.0.0.1:8765/login; then ok=1; echo "Shuinkan answered after ~$((i*3))s"; break; fi
  sleep 3
done
adb exec-out screencap -p > "$OUT/1-start.png" || true
if [ $ok = 1 ]; then python3 scripts/android_smoke_check.py 8765 || ok=0; fi
sleep 4; adb exec-out screencap -p > "$OUT/2-after.png" || true
adb logcat -d > "$OUT/logcat.txt" || true
echo "----- Python output -----"
grep -E "python\.std" "$OUT/logcat.txt" | tail -300 || true
echo "----- crashes -----"
grep -E "AndroidRuntime|FATAL|chaquopy" "$OUT/logcat.txt" | tail -80 || true
[ $ok = 1 ] || { echo "Shuinkan did not start or failed checks on the emulator"; exit 1; }
