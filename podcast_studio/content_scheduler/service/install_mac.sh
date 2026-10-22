#!/usr/bin/env bash
# Installs Content Scheduler as a launchd agent that starts at login and restarts if it stops.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
PLIST=~/Library/LaunchAgents/com.content-scheduler.plist
mkdir -p ~/Library/LaunchAgents
cat > "$PLIST" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.content-scheduler</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/tray.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$DIR/scheduler.log</string>
  <key>StandardErrorPath</key><string>$DIR/scheduler.log</string>
</dict></plist>
P
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed. Uninstall: launchctl unload $PLIST && rm $PLIST"
