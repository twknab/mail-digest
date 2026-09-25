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
  osascript -e 'display notification "claude is not on the scheduled PATH — no digest ran" with title "Mail digest" sound name "Ping"' 2>/dev/null
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

if ! "$CLAUDE" -p "$PROMPT" \
      --allowedTools "Bash(python3 $DIR/mail_digest.py:*)" \
      >>"$FILE" 2>>"$LOG"; then
  echo "$(date -Iseconds) claude exited non-zero; see $FILE" >>"$LOG"
  osascript -e 'display notification "The digest run failed — see digest.log" with title "Mail digest"' 2>/dev/null
  exit 1
fi

COUNT="$(grep -oE '^ACTION_ITEMS:[[:space:]]*[0-9]+' "$FILE" | grep -oE '[0-9]+' | tail -1)"

# An absent marker is NOT zero. Defaulting it to 0 makes "the model went
# off-script" indistinguishable from "nothing needs you" -- which would quietly
# swallow a real digest, and being told when something needs me is the whole
# product. Warn instead of reporting a number we did not read.
if [ -z "$COUNT" ]; then
  echo "$(date -Iseconds) WARNING no ACTION_ITEMS marker -> $FILE" >>"$LOG"
  osascript -e 'display notification "Digest ran but reported no item count — open it and check" with title "Mail digest" sound name "Ping"' 2>/dev/null
  exit 2
fi

if [ "$COUNT" -gt 0 ]; then
  PLURAL="items"; [ "$COUNT" -eq 1 ] && PLURAL="item"
  osascript -e "display notification \"$COUNT $PLURAL need you\" with title \"Mail digest\" subtitle \"$(date '+%H:%M')\" sound name \"Ping\"" 2>/dev/null
fi

echo "$(date -Iseconds) ok, $COUNT action items -> $FILE" >>"$LOG"
