#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$SCRIPT_DIR/logs"
VENV_DIR="$SCRIPT_DIR/.venv-mac"
DOWNLOADS_DIR="${DOWNLOADS_DIR:-$HOME/Downloads/Chrome_Downloads}"
PLIST_NAME="com.dlut.wechat-platform.plist"

mkdir -p "$PLIST_DIR" "$LOG_DIR"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q

cat > "$PLIST_DIR/$PLIST_NAME" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dlut.wechat-platform</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/python</string>
        <string>$SCRIPT_DIR/app.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/web.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/web.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
        <key>MASTER_DB_PATH</key>
        <string>$SCRIPT_DIR/wechat_master.db</string>
        <key>DB_PATH</key>
        <string>$SCRIPT_DIR/wechat_master.db</string>
        <key>DOWNLOADS_DIR</key>
        <string>$DOWNLOADS_DIR</string>
    </dict>
</dict>
</plist>
PLIST

launchctl unload "$PLIST_DIR/$PLIST_NAME" 2>/dev/null || true
launchctl load "$PLIST_DIR/$PLIST_NAME"

echo "wechat_platform 已启动: http://localhost:5001"
