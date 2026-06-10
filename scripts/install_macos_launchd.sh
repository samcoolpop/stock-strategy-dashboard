#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
UID_VALUE="$(id -u)"

MONITOR_LABEL="com.sam.stock-strategy.monitor"
CLOSE_SCAN_LABEL="com.sam.stock-strategy.close-scan"
MONITOR_PLIST="$LAUNCH_AGENTS_DIR/$MONITOR_LABEL.plist"
CLOSE_SCAN_PLIST="$LAUNCH_AGENTS_DIR/$CLOSE_SCAN_LABEL.plist"

cd "$PROJECT_ROOT"

mkdir -p "$LAUNCH_AGENTS_DIR" logs
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python -m src.jobs init-db

chmod +x scripts/run_monitor_and_push.sh scripts/run_close_scan_and_push.sh

cat > "$MONITOR_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$MONITOR_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/run_monitor_and_push.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Weekday</key><integer>1</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>10</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>1</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>15</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>1</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>20</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>2</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>10</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>2</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>15</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>2</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>20</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>3</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>10</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>3</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>15</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>3</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>20</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>4</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>10</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>4</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>15</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>4</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>20</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>5</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>10</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>5</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>15</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>5</integer>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>20</integer>
    </dict>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/monitor_launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/monitor_launchd.err.log</string>
</dict>
</plist>
PLIST

cat > "$CLOSE_SCAN_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$CLOSE_SCAN_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_ROOT/scripts/run_close_scan_and_push.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Weekday</key><integer>1</integer>
      <key>Hour</key><integer>15</integer>
      <key>Minute</key><integer>40</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>2</integer>
      <key>Hour</key><integer>15</integer>
      <key>Minute</key><integer>40</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>3</integer>
      <key>Hour</key><integer>15</integer>
      <key>Minute</key><integer>40</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>4</integer>
      <key>Hour</key><integer>15</integer>
      <key>Minute</key><integer>40</integer>
    </dict>
    <dict>
      <key>Weekday</key><integer>5</integer>
      <key>Hour</key><integer>15</integer>
      <key>Minute</key><integer>40</integer>
    </dict>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/logs/close_scan_launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/logs/close_scan_launchd.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$UID_VALUE" "$MONITOR_PLIST" 2>/dev/null || true
launchctl bootout "gui/$UID_VALUE" "$CLOSE_SCAN_PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$UID_VALUE" "$MONITOR_PLIST"
launchctl bootstrap "gui/$UID_VALUE" "$CLOSE_SCAN_PLIST"
launchctl enable "gui/$UID_VALUE/$MONITOR_LABEL"
launchctl enable "gui/$UID_VALUE/$CLOSE_SCAN_LABEL"

echo "Installed:"
echo "  $MONITOR_LABEL"
echo "  $CLOSE_SCAN_LABEL"
echo
echo "Plists:"
echo "  $MONITOR_PLIST"
echo "  $CLOSE_SCAN_PLIST"
echo
echo "Logs:"
echo "  $PROJECT_ROOT/logs/monitor_launchd.out.log"
echo "  $PROJECT_ROOT/logs/monitor_launchd.err.log"
echo "  $PROJECT_ROOT/logs/close_scan_launchd.out.log"
echo "  $PROJECT_ROOT/logs/close_scan_launchd.err.log"
