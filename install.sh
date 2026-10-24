#!/bin/sh
# Install the server as a macOS LaunchAgent: it starts at login and restarts if it stops.
# Run it again after moving the folder or to change the port; uninstall.sh removes it.
#
#   ./install.sh [--port 37690] [--label local.claude-mem-history-search] [--python /path/to/python3]
set -eu
REPO=$(cd "$(dirname "$0")" && pwd)
PORT=37690
LABEL=local.claude-mem-history-search
PYTHON=$(command -v python3 || true)
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT=$2; shift 2 ;;
    --label) LABEL=$2; shift 2 ;;
    --python) PYTHON=$2; shift 2 ;;
    *) echo "usage: $0 [--port N] [--label NAME] [--python PATH]" >&2; exit 2 ;;
  esac
done

[ "$(uname)" = Darwin ] || { echo "LaunchAgents are macOS only; run server.py another way (see README)." >&2; exit 1; }
case "$REPO" in *[\&\<\>\|]*) echo "the folder path can't contain & < > or |: $REPO" >&2; exit 1 ;; esac
[ -n "$PYTHON" ] || { echo "python3 not found; pass --python PATH" >&2; exit 1; }
PYTHON=$(cd "$(dirname "$PYTHON")" && pwd)/$(basename "$PYTHON")
"$PYTHON" -I -c 'import sys, sqlite3
assert sys.version_info >= (3, 9), "needs Python 3.9 or newer"
sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize=porter)")' \
  || { echo "$PYTHON can't run this (needs Python 3.9+ with SQLite FTS5)" >&2; exit 1; }
# Fails early, with a readable message, if claude-mem's database can't be found or is too old.
"$PYTHON" -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import indexer
problems = indexer.check_source(); [print(p, file=sys.stderr) for p in problems]; sys.exit(bool(problems))' "$REPO"

PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/claude-mem-history-search.log"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|@LABEL@|$LABEL|g" -e "s|@PYTHON@|$PYTHON|g" -e "s|@REPO@|$REPO|g" -e "s|@PORT@|$PORT|g" -e "s|@LOG@|$LOG|g" \
  "$REPO/launchd/claude-mem-history-search.plist.template" > "$PLIST"
plutil -lint -s "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
# bootout returns before the old copy is gone, and bootstrap fails (error 5) until it is.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break
  sleep 1
done
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed $PLIST"
echo "Open http://localhost:$PORT (the first start can take ~20 s while macOS checks Python's access to the folder)."
echo "Log: $LOG"
