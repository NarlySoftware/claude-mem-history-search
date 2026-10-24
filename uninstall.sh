#!/bin/sh
# Stop the LaunchAgent and remove it (install.sh puts it back). Leaves the folder and its index alone.
#   ./uninstall.sh [--label local.claude-mem-history-search]
set -eu
LABEL=local.claude-mem-history-search
[ "${1:-}" = --label ] && LABEL=$2
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || echo "$LABEL wasn't running"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Removed $LABEL"
