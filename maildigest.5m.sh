#!/bin/bash
# SwiftBar plugin. Symlink into your SwiftBar plugin folder:
#
#   ln -s "$PWD/maildigest.5m.sh" ~/SwiftBar/maildigest.5m.sh
#
# The 5m is SwiftBar's refresh interval. It reads only files the scheduled run
# already wrote -- it never touches a mailbox, so refreshing costs nothing and
# cannot mark anything read.

DIR="${MAIL_DIGEST_DIR:-$HOME/Development/mail-digest}"
OUT="$DIR/digests"
LOG="$DIR/digest.log"
STATE="$HOME/.mail-digest"

# SwiftBar runs bash= with a minimal PATH. viewer.py is stdlib-only, so prefer
# the system interpreter, which is always present and needs no environment. A
# pyenv shim would need pyenv itself resolvable and could silently do nothing.
if [ -x /usr/bin/python3 ]; then
  PY3=/usr/bin/python3
else
  PY3="$(command -v python3 2>/dev/null || echo python3)"
fi

GREEN="#4a9d6e"
ORANGE="#e09055"
GREY="#8a8782"

menu_actions() {
  echo "---"
  echo "View latest digest | bash=$PY3 param1=$DIR/viewer.py terminal=false"
  echo "All digests | bash=$PY3 param1=$DIR/viewer.py param2=--list terminal=false"
  echo "Run now | bash=/bin/launchctl param1=kickstart param2=-k param3=gui/$(id -u)/local.mail-digest terminal=false refresh=true"
}

latest="$(ls -t "$OUT"/*.md 2>/dev/null | head -1)"

# A run in flight publishes epoch|percent|label. Show a bar while that is
# fresh; a stale file means the run died without clearing it, so ignore it
# rather than leaving a bar on screen forever.
STATUS_FILE="$STATE/status"
if [ -f "$STATUS_FILE" ]; then
  IFS='|' read -r st_at st_pct st_label < "$STATUS_FILE"
  st_age=$(( $(date +%s) - ${st_at:-0} ))
  if [ "$st_age" -ge 0 ] && [ "$st_age" -lt 300 ] && [ -n "$st_pct" ]; then
    # Round up, so a run that has started never renders as an empty bar and
    # look stalled; and cap at 10 so 100% cannot overflow.
    filled=$(( (st_pct + 9) / 10 ))
    [ "$filled" -gt 10 ] && filled=10
    bar=""
    for i in 1 2 3 4 5 6 7 8 9 10; do
      if [ "$i" -le "$filled" ]; then bar="$bar▰"; else bar="$bar▱"; fi
    done
    # The bar belongs in the dropdown, not the menu bar -- a bar that changes
    # width every few seconds shoves every other menu bar icon around.
    echo "● | color=$GREY size=11"
    echo "---"
    echo "${st_label:-working} · ${st_pct}% | color=$GREY"
    echo "$bar | color=$GREY size=13 font=Menlo"
    menu_actions
    echo "---"
    tail -1 "$LOG" 2>/dev/null | sed 's/$/ | size=10 color=#8a8782/'
    exit 0
  fi
fi


if [ -z "$latest" ]; then
  echo "● | color=$GREY size=11"
  echo "---"
  echo "No digest yet | color=$GREY"
  menu_actions
  exit 0
fi

stem="$(basename "$latest" .md)"
count="$(grep -oE '^ACTION_ITEMS:[[:space:]]*[0-9]+' "$latest" | grep -oE '[0-9]+' | tail -1)"
acked="$(cat "$STATE/acknowledged" 2>/dev/null || true)"
when="$(echo "$stem" | sed -E 's/^[0-9]{4}-([0-9]{2})-([0-9]{2})-([0-9]{2})([0-9]{2})$/\1\/\2 \3:\4/')"

# A digest still being written has no marker yet, and an absent marker is not
# zero -- the same distinction run-digest.sh makes. Stay quiet about a file
# younger than 90s rather than crying wolf mid-run.
age=$(( $(date +%s) - $(stat -f %m "$latest") ))

# A negative age means a future mtime (clock skew): treat it as old, so a
# genuinely broken digest is never masked as "in progress".
if [ -z "$count" ] && [ "$age" -ge 0 ] && [ "$age" -lt 90 ]; then
  echo "● | color=$GREY size=11"
  echo "---"
  echo "Digest in progress… | color=$GREY"
elif [ -z "$count" ]; then
  echo "● | color=$ORANGE size=11"
  echo "---"
  echo "Last digest reported no item count | color=$ORANGE"
  echo "Open it and check | color=$GREY size=12"
elif [ "$count" -gt 0 ] && [ "$acked" != "$stem" ]; then
  echo "● $count | color=$ORANGE size=11"
  echo "---"
  echo "$count need you · $when | color=$GREY"
else
  echo "● | color=$GREEN size=11"
  echo "---"
  if [ "$count" -gt 0 ]; then
    echo "All caught up · $count seen · $when | color=$GREY"
  else
    echo "All caught up · $when | color=$GREY"
  fi
fi

# Items, only while there is something outstanding.
if [ -n "$count" ] && [ "$count" -gt 0 ] && [ "$acked" != "$stem" ]; then
  echo "---"
  awk '
    /^### / { sub(/^### /, ""); print "▾ " $0 " | color=#8a8782 size=12"; bucket=""; next }
    /^\*\*Needs action\*\*/ { bucket="act"; next }
    /^\*\*Worth knowing\*\*/ { bucket="fyi"; next }
    /\*\*Subject:\*\*/ {
        sub(/^.*\*\*Subject:\*\*[[:space:]]*/, "");
        if (length($0) > 58) $0 = substr($0, 1, 55) "...";
        if (bucket == "fyi") print "   " $0 " | size=11 color=#8a8782";
        else print "   • " $0 " | size=12";
        next
    }
  ' "$latest"
  echo "---"
  echo "Mark all caught up | bash=$DIR/ack.sh terminal=false refresh=true"
fi

menu_actions
echo "---"
tail -1 "$LOG" 2>/dev/null | sed 's/$/ | size=10 color=#8a8782/'
