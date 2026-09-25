#!/bin/bash
# SwiftBar plugin. Copy or symlink into your SwiftBar plugin folder:
#
#   ln -s "$PWD/maildigest.5m.sh" ~/SwiftBar/maildigest.5m.sh
#
# The 5m in the filename is SwiftBar's refresh interval. It only reads files
# the scheduled run already wrote -- it never touches a mailbox, so refreshing
# it costs nothing and cannot mark anything read.

DIR="${MAIL_DIGEST_DIR:-$HOME/Development/mail-digest}"
OUT="$DIR/digests"
LOG="$DIR/digest.log"

latest="$(ls -t "$OUT"/*.md 2>/dev/null | head -1)"

if [ -z "$latest" ]; then
  echo "· | sfimage=envelope"
  echo "---"
  echo "No digest yet | color=gray"
  echo "Run now | bash=/bin/launchctl param1=kickstart param2=-k param3=gui/$(id -u)/local.mail-digest terminal=false refresh=true"
  exit 0
fi

count="$(grep -oE '^ACTION_ITEMS:[[:space:]]*[0-9]+' "$latest" | grep -oE '[0-9]+' | tail -1)"
when="$(basename "$latest" .md | sed -E 's/^([0-9]{4})-([0-9]{2})-([0-9]{2})-([0-9]{2})([0-9]{2})$/\2\/\3 \4:\5/')"

# An absent marker is not zero -- say so rather than reporting a number we did
# not read, the same distinction run-digest.sh makes.
if [ -z "$count" ]; then
  echo "?! | sfimage=exclamationmark.triangle color=orange"
  echo "---"
  echo "Last digest had no item count | color=orange"
elif [ "$count" -gt 0 ]; then
  echo "$count | sfimage=envelope.badge color=#d08770"
  echo "---"
  echo "$count need you · $when | color=gray"
else
  echo "· | sfimage=envelope"
  echo "---"
  echo "Nothing needs you · $when | color=gray"
fi

echo "---"

# Section headings are the inboxes; Subject lines are the items.
# Track which bucket we are in, so "2 need you" never sits above three items.
# Actionable ones lead; Worth knowing is dimmed so the count stays honest.
awk '
  /^### / { sub(/^### /, ""); print "▾ " $0 " | color=gray size=12"; bucket=""; next }
  /^\*\*Needs action\*\*/ { bucket="act"; next }
  /^\*\*Worth knowing\*\*/ { bucket="fyi"; next }
  /\*\*Subject:\*\*/ {
      sub(/^.*\*\*Subject:\*\*[[:space:]]*/, "");
      if (length($0) > 58) $0 = substr($0, 1, 55) "...";
      if (bucket == "fyi") print "   " $0 " | size=11 color=gray";
      else print "   • " $0 " | size=12";
      next
  }
' "$latest"

echo "---"
echo "Open latest digest | bash=/usr/bin/open param1=$latest terminal=false"
echo "Open digests folder | bash=/usr/bin/open param1=$OUT terminal=false"
echo "Run now | bash=/bin/launchctl param1=kickstart param2=-k param3=gui/$(id -u)/local.mail-digest terminal=false refresh=true"
echo "---"
tail -1 "$LOG" 2>/dev/null | sed 's/$/ | size=10 color=gray/'
