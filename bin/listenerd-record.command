#!/bin/bash
# Doubleclick-launched recorder. Runs inside Terminal.app, which is convenient
# for live debugging (you see whisper/ollama output as it streams).
# For the unobtrusive menu-bar workflow, use extras/listenerd-recorder.app instead.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${LISTENERD_LOG:-$HOME/Library/Logs/listenerd-record.log}"
UV="${UV:-/opt/homebrew/bin/uv}"
mkdir -p "$(dirname "$LOG")"
cd "$REPO"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') launch via .command ===" | tee -a "$LOG"
"$UV" run listenerd record -v 2>&1 | tee -a "$LOG"
status=${PIPESTATUS[0]}
echo "=== exit $status ===" | tee -a "$LOG"
if [[ $status -ne 0 ]]; then
  echo
  echo "Recorder exited with status $status. Press Return to close."
  read -r
fi
