#!/bin/bash
# <swiftbar.title>Mail Digest</swiftbar.title>
# <swiftbar.author>timknab</swiftbar.author>
# <swiftbar.desc>Digests of the mail that actually needs you.</swiftbar.desc>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>false</swiftbar.hideSwiftBar>
#
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
# Soft, not alarming: this menu is opened many times a day, and a wall of red
# stops meaning anything. The step between them is enough to scan.
U_HIGH="#d9826f"
U_MED="#c9975f"
U_LOW="#8f9295"

menu_actions() {
  echo "---"
  # Sort by NAME, not mtime: regenerating every page gives them all the same
  # mtime, and the filenames are already timestamps.
  latest_html="$(ls -1 "$VIEW"/2*.html 2>/dev/null | sort -r | head -1)"
  [ -n "$latest_html" ] && echo "View latest digest | href=file://$latest_html"
  [ -f "$VIEW/index.html" ] && echo "All digests | href=file://$VIEW/index.html"
  echo "Run now | shell=/bin/sh param1=-c param2=\"/bin/launchctl kickstart -k gui/$(id -u)/local.mail-digest\" terminal=false refresh=true"
  echo "---"
  # The About content lives here as a submenu rather than only behind a click,
  # so the entry is never an empty menu.
  # One entry. The blurb and the timknab.dev credit live in the About window
  # itself, not scattered through a context menu.
  #
  # Note: SwiftBar appends its own section below this -- "Run in Terminal",
  # "Disable Plugin" and an "About" that is SwiftBar's, not ours. That one
  # cannot be changed from a plugin.
  echo "About | shell=$DIR/about.sh terminal=false"
}

latest="$(ls -t "$OUT"/*.md 2>/dev/null | head -1)"

# Render the HTML here, so the menu items are plain href= links that SwiftBar
# opens itself. Shelling out on click meant sh -> python -> open, three places
# to fail silently, and a menu item that does nothing gives no clue why.
VIEW="$HOME/.mail-digest/view"
"$PY3" "$DIR/viewer.py" --about --no-open >/dev/null 2>&1
"$PY3" "$DIR/viewer.py" --no-open >/dev/null 2>&1

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
  # The dot takes the colour of the worst thing waiting, so the menu bar says
  # how bad rather than only how many. open_items() sorts most urgent first.
  top="$(printf '%s\n' "$open_tsv" | head -1 | cut -f4)"
  case "$top" in
    high) dot="$U_HIGH" ;;
    low)  dot="$U_LOW" ;;
    *)    dot="$U_MED" ;;
  esac
  echo "● $open_n | color=$dot size=11"
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
  printf '%s\n' "$open_tsv" | while IFS="$(printf '\t')" read -r id inbox subject urg; do
    [ -n "$id" ] || continue
    short="$subject"
    [ ${#short} -gt 54 ] && short="$(printf '%.51s...' "$short")"
    case "$urg" in
      high) c="$U_HIGH" ;;
      low)  c="$U_LOW" ;;
      *)    c="$U_MED" ;;
    esac
    echo "• $short | color=$c shell=/bin/sh param1=-c param2=\"$PY3 $DIR/triage.py --done $id\" terminal=false refresh=true"
    echo "   $inbox | color=$GREY size=11"
  done
fi

menu_actions
echo "---"
tail -1 "$LOG" 2>/dev/null | sed 's/$/ | size=10 color=#8a8782/'
