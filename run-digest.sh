#!/bin/bash
# Scheduled entry point. Runs the digest, saves it, and notifies only when
# something actually needs me -- a quiet inbox stays quiet.
set -uo pipefail

# Resolve our own location, so this works from any projects directory rather
# than only from ~/mail-digest.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$DIR/digests"
LOG="$DIR/digest.log"
mkdir -p "$OUT"

# Delivering a notification on macOS is not guaranteed, and the failure is
# usually silent -- which is the worst possible outcome here, because a
# notification that never arrives looks exactly like a quiet inbox.
#
# So: try each route in order of how well it reports failure, and LOG the
# outcome either way. If every route fails, say so loudly in the log rather
# than letting the run look successful.
#
#   terminal-notifier  properly signed, and exits non-zero when macOS refuses
#   SwiftBar           properly signed; present if you use the menu bar plugin
#   osascript          last resort; returns 0 even when the notification is
#                      dropped, so it can never be trusted on its own
#
# A locally compiled AppleScript applet was tried and removed: macOS will not
# register an ad-hoc-signed app with Notification Center, so it ran cleanly,
# exited 0, and delivered nothing -- the exact failure this guards against.
notify() {
  local message="$1" subtitle="${2:-}" route=""

  if command -v terminal-notifier >/dev/null 2>&1; then
    if terminal-notifier -title "Mail digest" -subtitle "$subtitle" \
         -message "$message" -sound Ping >/dev/null 2>&1; then
      route="terminal-notifier"
    fi
  fi

  if [ -z "$route" ] && [ -d "/Applications/SwiftBar.app" ]; then
    if open "swiftbar://notify?plugin=maildigest&title=Mail%20digest&body=$(printf %s "$message" | sed 's/ /%20/g')" 2>/dev/null; then
      route="swiftbar"
    fi
  fi

  if [ -z "$route" ]; then
    osascript -e "display notification \"$message\" with title \"Mail digest\"" 2>/dev/null && route="osascript(unverified)"
  fi

  if [ -z "$route" ]; then
    echo "$(date -Iseconds) NOTIFY FAILED (every route refused): $message" >>"$LOG"
  else
    echo "$(date -Iseconds) notified via $route: $message" >>"$LOG"
  fi
}

# Publish coarse stages for the menu bar. mail_digest.py fills in the detail
# between them, since claude -p is opaque from out here. Each stage pushes a
# refresh because SwiftBar's own interval is far slower than a run.
STATUS="$HOME/.mail-digest/status"
stage() {
  mkdir -p "$HOME/.mail-digest" 2>/dev/null
  printf '%s|%s|%s\n' "$(date +%s)" "$1" "$2" >"$STATUS" 2>/dev/null
  [ -d /Applications/SwiftBar.app ] && open -g "swiftbar://refreshplugin?name=maildigest" >/dev/null 2>&1
  return 0   # never let a missing menu bar affect the run's exit status
}
end_stage() {
  rm -f "$STATUS" 2>/dev/null
  [ -d /Applications/SwiftBar.app ] && open -g "swiftbar://refreshplugin?name=maildigest" >/dev/null 2>&1
  return 0   # this runs as an EXIT trap; it must not disturb the exit status
}
# Never leave a stale bar on screen if the run dies part way.
trap end_stage EXIT

stage 3 "starting"

STAMP="$(date +%Y-%m-%d-%H%M)"
FILE="$OUT/$STAMP.md"

# launchd starts with a nearly empty PATH, so find claude explicitly rather
# than hoping the login shell's PATH is present.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
CLAUDE="$(command -v claude || true)"
if [ -z "$CLAUDE" ]; then
  # Nobody is watching at 08:07. A silent exit here looks exactly like a quiet
  # inbox, so this failure has to be as loud as any other.
  echo "$(date -Iseconds) claude not on PATH ($PATH)" >>"$LOG"
  notify "claude is not on the scheduled PATH — no digest ran"
  exit 127
fi

{
  echo "# Mail digest — $(date '+%A %-d %B %Y, %H:%M')"
  echo
} >"$FILE"

# The prompt says ~/mail-digest for readability, but --allowedTools matches on
# a literal prefix, so ~ must be expanded or every run stalls on a permission
# prompt with nobody there to answer it.
PROMPT="$(sed "s|~/mail-digest|$DIR|g" "$DIR/prompt-digest.md")"

stage 8 "connecting"

if ! "$CLAUDE" -p "$PROMPT" \
      --allowedTools "Bash(python3 $DIR/mail_digest.py:*)" \
      >>"$FILE" 2>>"$LOG"; then
  echo "$(date -Iseconds) claude exited non-zero; see $FILE" >>"$LOG"
  notify "The digest run failed — see digest.log"
  exit 1
fi

stage 92 "writing digest"

COUNT="$(grep -oE '^ACTION_ITEMS:[[:space:]]*[0-9]+' "$FILE" | grep -oE '[0-9]+' | tail -1)"

# An absent marker is NOT zero. Defaulting it to 0 makes "the model went
# off-script" indistinguishable from "nothing needs you" -- which would quietly
# swallow a real digest, and being told when something needs me is the whole
# product. Warn instead of reporting a number we did not read.
if [ -z "$COUNT" ]; then
  echo "$(date -Iseconds) WARNING no ACTION_ITEMS marker -> $FILE" >>"$LOG"
  notify "Digest ran but reported no item count — open it and check"
  exit 2
fi

if [ "$COUNT" -gt 0 ]; then
  PLURAL="items"; [ "$COUNT" -eq 1 ] && PLURAL="item"
  notify "$COUNT $PLURAL need you" "$(date '+%H:%M')"
fi

echo "$(date -Iseconds) ok, $COUNT action items -> $FILE" >>"$LOG"
