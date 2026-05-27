#!/usr/bin/env bash
# SwiftBar plugin: start/stop the listenerd recorder from the menu bar.
# Refresh interval is encoded in the filename (3s).
#
# Install: symlink this file into your SwiftBar plugin directory, e.g.
#   ln -s "$PWD/extras/swiftbar/listenerd.3s.sh" \
#         ~/.config/swiftbar/Plugins/listenerd.3s.sh
#
# <swiftbar.title>listenerd</swiftbar.title>
# <swiftbar.author>Lukas Hartrumpf</swiftbar.author>
# <swiftbar.desc>Manual start/stop for the listenerd recorder.</swiftbar.desc>

SELF="$(/usr/bin/python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$0")"
REPO="$(cd "$(dirname "$SELF")/../.." && pwd)"
CTL="$REPO/bin/listenerd-ctl"
MEETINGS="$HOME/Meetings"
LOGFILE="$HOME/Library/Logs/listenerd-record.log"

state="$("$CTL" status 2>/dev/null || echo unknown)"

case "$state" in
  recording)
    echo "🔴 REC | color=red"
    echo "---"
    echo "Stop Recording | bash='$CTL' param1=stop terminal=false refresh=true"
    ;;
  processing)
    # Transcribing + summarizing. Don't offer Stop — signals are ignored
    # during this phase anyway, and clicking again is what got people in
    # trouble before.
    echo "⏳ processing… | color=orange"
    echo "---"
    echo "Processing transcript + summary (no input) | disabled=true"
    ;;
  *)
    echo "⚪︎"
    echo "---"
    echo "Start Recording | bash='$CTL' param1=start terminal=false refresh=true"
    ;;
esac

echo "---"
echo "Open Meetings folder | bash=/usr/bin/open param1='$MEETINGS' terminal=false"
echo "Tail log | bash=/usr/bin/open param1=-a param2=Terminal param3='$LOGFILE' terminal=false"
echo "Refresh | refresh=true"
