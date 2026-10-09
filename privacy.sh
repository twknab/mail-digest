#!/bin/bash
# What of your mail is on this disk, and how to get rid of it.
#
#   ./privacy.sh                      # report only
#   ./privacy.sh --purge-older-than 30
#   ./privacy.sh --purge-all
#
# Digests are summaries of real mail in plaintext. They are useful to keep and
# they are also the thing worth deleting, so this makes both the amount and the
# removal explicit rather than letting them accumulate unexamined.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$HOME/.mail-digest"
MODE="${1:-report}"
DAYS="${2:-}"

# Count with find, not `ls "$glob"` -- a quoted glob never expands, which
# silently reported zero of everything.
count() { find "$1" -maxdepth 1 -name "$2" 2>/dev/null | wc -l | tr -d ' '; }
size()  { du -sh "$1" 2>/dev/null | cut -f1 | tr -d ' ' || echo "0B"; }
row()   { printf "  %-22s %7s  %s\n" "$1" "$2" "$3"; }

report() {
  echo "Mail content stored on this machine"
  echo
  row "digests/" "$(size "$DIR/digests")" "$(count "$DIR/digests" '*.md') digests — summaries of real mail"
  row "~/.mail-digest/view/" "$(size "$STATE/view")" "$(count "$STATE/view" '*.html') pages — the same, rendered"
  row "items.json" "$(size "$STATE/items.json")" "$(python3 -c "
import json,sys
try: print(len(json.load(open('$STATE/items.json'))['items']))
except Exception: print(0)" 2>/dev/null) items — subject and sender only"
  if [ -s "$STATE/sweep-batch.json" ]; then
    row "sweep-batch.json" "$(size "$STATE/sweep-batch.json")" "LEFTOVER — may hold message bodies"
  fi
  row "state.json" "$(size "$STATE/state.json")" "UIDs only — no mail content"
  echo
  oldest="$(ls -tr "$DIR/digests"/*.md 2>/dev/null | head -1)"
  [ -n "$oldest" ] && echo "  Oldest: $(basename "$oldest" .md)"
  echo
  echo "  None of this is encrypted, and none of it is in git (digests/ is ignored)."
  echo "  Passwords are not here — they are in the Keychain."
}

case "$MODE" in
report) report ;;
--purge-older-than)
  [ -n "$DAYS" ] || { echo "usage: $0 --purge-older-than <days>" >&2; exit 1; }
  n=$(find "$DIR/digests" -name '*.md' -mtime "+$DAYS" 2>/dev/null | wc -l | tr -d ' ')
  v=$(find "$STATE/view" -name '*.html' -mtime "+$DAYS" 2>/dev/null | wc -l | tr -d ' ')
  find "$DIR/digests" -name '*.md' -mtime "+$DAYS" -delete 2>/dev/null || true
  find "$STATE/view" -name '*.html' -mtime "+$DAYS" -delete 2>/dev/null || true
  echo "Removed $n digest(s) and $v rendered page(s) older than $DAYS days."
  echo "Open items are untouched — they hold only subject and sender."
  ;;
--purge-all)
  printf "Delete every stored digest and rendered page? Open items stay. [y/N] "
  read -r a
  case "$a" in
    y|Y)
      rm -f "$DIR"/digests/*.md "$STATE"/view/*.html "$STATE/sweep-batch.json" 2>/dev/null || true
      echo "Done. Nothing summarised from your mail remains on disk."
      ;;
    *) echo "Cancelled." ;;
  esac
  ;;
*) echo "usage: $0 [--purge-older-than <days> | --purge-all]" >&2; exit 1 ;;
esac
