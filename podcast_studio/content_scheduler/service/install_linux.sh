#!/usr/bin/env bash
# Starts Content Scheduler (tray icon) automatically when you log in to your desktop.
# Use --headless instead to install a systemd user service without a tray icon (servers / Raspberry Pi).
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
if [ "$1" = "--headless" ]; then
  mkdir -p ~/.config/systemd/user
  cat > ~/.config/systemd/user/content-scheduler.service <<UNIT
[Unit]
Description=Content Scheduler
After=network-online.target
[Service]
WorkingDirectory=$DIR
ExecStart=$PY $DIR/app.py
Restart=always
RestartSec=10
[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload && systemctl --user enable --now content-scheduler
  loginctl enable-linger "$USER" 2>/dev/null || true
  echo "Installed headless service. Uninstall: systemctl --user disable --now content-scheduler"
  exit 0
fi
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/content-scheduler.desktop <<D
[Desktop Entry]
Type=Application
Name=Content Scheduler
Exec=$PY $DIR/tray.py
Path=$DIR
X-GNOME-Autostart-enabled=true
D
nohup "$PY" "$DIR/tray.py" >/dev/null 2>&1 &
echo "Installed: starts at login. Uninstall: rm ~/.config/autostart/content-scheduler.desktop"
echo "GNOME needs the 'AppIndicator and KStatusNotifierItem Support' extension to show tray icons."
