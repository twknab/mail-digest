#!/bin/bash
# Start the count from now, with a native confirmation.
#
# A menu item that closes 38 items on a stray click would be a bad trade, so
# this asks first through a real dialog rather than passing --yes.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY3=/usr/bin/python3
[ -x "$PY3" ] || PY3="$(command -v python3)"

COUNT="$("$PY3" "$DIR/triage.py" --tsv 2>/dev/null | grep -c . || echo 0)"
URGENT="$("$PY3" "$DIR/triage.py" --tsv 2>/dev/null | cut -f4 | grep -c '^high$' || echo 0)"

if [ "$COUNT" -eq 0 ]; then
  osascript -e 'display dialog "Nothing is open — the count is already zero." with title "Mail Digest" buttons {"OK"} default button "OK"' >/dev/null 2>&1
  exit 0
fi

MSG="Mark all $COUNT open item(s) as cleared and start the count from now?"
[ "$URGENT" -gt 0 ] && MSG="$MSG

$URGENT of them are urgent."
MSG="$MSG

Nothing is deleted. They stay in the record and the reset can be undone."

ICON="$DIR/docs/icon.icns"
if [ -f "$ICON" ]; then
  ANSWER="$(osascript <<EOF 2>/dev/null
display dialog "$MSG" with title "Start fresh" ¬
  buttons {"Cancel", "Start fresh"} default button "Cancel" ¬
  with icon (POSIX file "$ICON")
EOF
)"
else
  ANSWER="$(osascript -e "display dialog \"$MSG\" with title \"Start fresh\" buttons {\"Cancel\", \"Start fresh\"} default button \"Cancel\"" 2>/dev/null)"
fi

case "$ANSWER" in
  *"Start fresh"*)
    OUT="$("$PY3" "$DIR/triage.py" --clear --yes 2>&1)"
    STAMP="$(printf '%s' "$OUT" | grep -oE '\-\-undo-clear .*' | awk '{print $2}')"
    osascript -e "display notification \"Count reset — $COUNT item(s) cleared\" with title \"Mail Digest\"" >/dev/null 2>&1
    printf '%s\n' "$OUT"
    [ -n "$STAMP" ] && echo "$STAMP" > "$HOME/.mail-digest/last-reset"
    ;;
  *) echo "Cancelled." ;;
esac
