#!/bin/bash
# インストール済みの認証情報は gh / claude が管理する。plist に秘密情報を含めない。
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.arakitakashi.ai-journal"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/.local/logs"
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/$LABEL"
fi
/usr/bin/plutil -create xml1 "$PLIST"
/usr/bin/plutil -insert Label -string "$LABEL" "$PLIST"
/usr/bin/plutil -insert ProgramArguments -json "[]" "$PLIST"
/usr/bin/plutil -insert ProgramArguments.0 -string /bin/bash "$PLIST"
/usr/bin/plutil -insert ProgramArguments.1 -string "$PROJECT_DIR/scripts/run.sh" "$PLIST"
/usr/bin/plutil -insert RunAtLoad -bool YES "$PLIST"
/usr/bin/plutil -insert StartInterval -integer 1800 "$PLIST"
/usr/bin/plutil -insert StandardOutPath -string "$PROJECT_DIR/.local/logs/launchd.out.log" "$PLIST"
/usr/bin/plutil -insert StandardErrorPath -string "$PROJECT_DIR/.local/logs/launchd.err.log" "$PLIST"
/usr/bin/plutil -lint "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl print "gui/$(id -u)/$LABEL"
