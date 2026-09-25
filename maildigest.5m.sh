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
BLUE="#4a90d9"

menu_actions() {
  echo "---"
  echo "View latest digest | shell=/bin/sh param1=-c param2=\"$PY3 $DIR/viewer.py\" terminal=false"
  echo "All digests | shell=/bin/sh param1=-c param2=\"$PY3 $DIR/viewer.py --list\" terminal=false"
  echo "Run now | shell=/bin/sh param1=-c param2=\"/bin/launchctl kickstart -k gui/$(id -u)/local.mail-digest\" terminal=false refresh=true"
  echo "---"
  # The About content lives here as a submenu rather than only behind a click,
  # so the entry is never an empty menu.
  # Flat lines, no submenu: "--" is SwiftBar's submenu prefix and getting that
  # structure subtly wrong renders an empty menu with no error anywhere.
  echo "Mail Digest | size=13"
  echo "Three weekday digests of the mail that needs you | color=$GREY size=11"
  echo "Read-only — a run never marks mail as read | color=$GREY size=11"
  echo "Replies are drafted, never sent | color=$GREY size=11"
  echo "Open the About page | shell=/bin/sh param1=-c param2=\"$PY3 $DIR/viewer.py --about\" terminal=false"
  echo "timknab.dev | href=https://timknab.dev color=$BLUE"
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

    # A hollow blue circle just means "running". The dropdown carries the
    # detail, so the menu bar does not need to animate -- and a glyph that
    # changes on every refresh is noise for something that lasts 15 seconds.
    echo "○ | color=$BLUE size=11"
    echo "---"
    echo "${st_label:-working} · ${st_pct}% | color=$BLUE"
    echo "$bar | color=$BLUE size=13 font=Menlo"
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
# Sweep files carry a prefix; strip it so the label stays a readable time.
when="$(echo "$stem" | sed -E 's/^sweep-//; s/^[0-9]{4}-([0-9]{2})-([0-9]{2})-([0-9]{2})([0-9]{2})$/\1\/\2 \3:\4/')"
case "$stem" in sweep-*) when="$when (sweep)";; esac

# What is still open is the list, not the last run. An item raised this morning
# is still open this evening even though the newest digest is empty.
open_tsv="$("$PY3" "$DIR/triage.py" --tsv 2>/dev/null)"
open_n=0
[ -n "$open_tsv" ] && open_n=$(printf '%s\n' "$open_tsv" | wc -l | tr -d ' ')

# A digest still being written has no marker yet, and an absent marker is not
# zero -- the same distinction run-digest.sh makes. A negative age means a
# future mtime (clock skew): treat it as old, so a genuinely broken digest is
# never masked as "in progress".
age=$(( $(date +%s) - $(stat -f %m "$latest") ))

if [ -z "$count" ] && [ "$age" -ge 0 ] && [ "$age" -lt 90 ]; then
  echo "○ | color=$BLUE size=11"
  echo "---"
  echo "Digest in progress… | color=$GREY"
elif [ -z "$count" ]; then
  echo "● | color=$ORANGE size=11"
  echo "---"
  echo "Last digest reported no item count | color=$ORANGE"
  echo "Open it and check | color=$GREY size=12"
elif [ "$open_n" -gt 0 ]; then
  echo "● $open_n | color=$ORANGE size=11"
  echo "---"
  echo "$open_n open · last run $when | color=$GREY"
else
  echo "● | color=$GREEN size=11"
  echo "---"
  echo "All caught up · $when | color=$GREY"
fi

if [ "$open_n" -gt 0 ]; then
  echo "---"
  echo "Click an item to mark it done | color=$GREY size=11"
  printf '%s\n' "$open_tsv" | while IFS="$(printf '\t')" read -r id inbox subject; do
    [ -n "$id" ] || continue
    short="$subject"
    [ ${#short} -gt 54 ] && short="$(printf '%.51s...' "$short")"
    echo "• $short | shell=/bin/sh param1=-c param2=\"$PY3 $DIR/triage.py --done $id\" terminal=false refresh=true"
    echo "   $inbox | color=$GREY size=11"
  done
fi

menu_actions
echo "---"
tail -1 "$LOG" 2>/dev/null | sed 's/$/ | size=10 color=#8a8782/'
