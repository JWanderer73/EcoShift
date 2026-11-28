#!/bin/sh
# Install the morning price-window job for this user. No sudo.
# The job runs at 07:15 in the Mac's local time. It does not start now.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
PY="$ROOT/.venv/bin/python"
LABEL=com.ecoshift.price-windows-daily
if [ ! -x "$PY" ]; then
  echo "missing $PY" >&2
  exit 1
fi
mkdir -p "$ROOT/price_windows/cache" "$ROOT/price_windows/reports" "$HOME/Library/LaunchAgents"
write_plist() {
  cat > "$1" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY}</string>
    <string>-m</string>
    <string>price_windows.daily</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>7</integer>
    <key>Minute</key>
    <integer>15</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${ROOT}/price_windows/cache/daily.log</string>
  <key>StandardErrorPath</key>
  <string>${ROOT}/price_windows/cache/daily.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TZ</key>
    <string>America/Los_Angeles</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
</dict>
</plist>
EOF
}
write_plist "$ROOT/price_windows/com.ecoshift.price-windows-daily.plist"
DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
write_plist "$DEST"
UID_NUM=$(id -u)
launchctl bootout "gui/${UID_NUM}" "$DEST" 2>/dev/null || true
launchctl bootstrap "gui/${UID_NUM}" "$DEST"
echo "Installed ${LABEL} at 07:15 local time."
echo "Command: ${PY} -m price_windows.daily"
echo "Log: ${ROOT}/price_windows/cache/daily.log"
