#!/bin/bash
# Swap the menu bar to sample data so it can be screenshotted, then swap back.
#
#   ./demo-mode.sh on     # fake items + a fake digest; real state backed up
#   ./demo-mode.sh off    # restore
#
# Exists so a screenshot of the menu can show the real UI with none of your
# mail in it. Masking a real screenshot is worse: it is fiddly, and one missed
# region publishes something.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$HOME/.mail-digest"
BACKUP="$STATE/demo-backup"

refresh() { [ -d /Applications/SwiftBar.app ] && open -g "swiftbar://refreshallplugins" >/dev/null 2>&1 || true; }

case "${1:-}" in
on)
  if [ -d "$BACKUP" ]; then
    echo "Already in demo mode. Run './demo-mode.sh off' first."
    exit 1
  fi
  mkdir -p "$BACKUP"
  [ -f "$STATE/items.json" ] && cp "$STATE/items.json" "$BACKUP/items.json"
  mkdir -p "$BACKUP/digests" && cp -R "$DIR/digests/." "$BACKUP/digests/" 2>/dev/null || true

  cat > "$STATE/items.json" <<'JSON'
{
  "items": {
    "work:4821": {"id":"work:4821","account":"work","uid":4821,
      "subject":"Q3 statement of work — signature needed","who":"Dana Ruiz",
      "inbox":"work@example.com","role":"business","state":"open",
      "first_seen":"2026-03-12T15:07:00+00:00","digest":"2026-03-12-0807","closed_at":null},
    "work:4816": {"id":"work:4816","account":"work","uid":4816,
      "subject":"Payment could not be processed","who":"Acme Utilities",
      "inbox":"work@example.com","role":"business","state":"open",
      "first_seen":"2026-03-12T15:07:01+00:00","digest":"2026-03-12-0807","closed_at":null},
    "personal:991": {"id":"personal:991","account":"personal","uid":991,
      "subject":"Security release 2.4.1 — please update","who":"Open Source Project",
      "inbox":"me@example.com","role":"personal","state":"open",
      "first_seen":"2026-03-12T15:07:02+00:00","digest":"2026-03-12-0807","closed_at":null}
  }
}
JSON

  rm -f "$DIR"/digests/*.md
  cat > "$DIR/digests/2026-03-12-0807.md" <<'MD'
# Mail digest — Thursday 12 March 2026, 08:07

Sample data.

ACTION_ITEMS: 3
MD
  refresh
  echo "Demo mode ON. The menu now shows sample data."
  echo "Real state is in $BACKUP — run './demo-mode.sh off' to restore."
  ;;
off)
  if [ ! -d "$BACKUP" ]; then
    echo "Not in demo mode; nothing to restore."
    exit 0
  fi
  rm -f "$DIR"/digests/*.md
  cp -R "$BACKUP/digests/." "$DIR/digests/" 2>/dev/null || true
  if [ -f "$BACKUP/items.json" ]; then
    cp "$BACKUP/items.json" "$STATE/items.json"
  else
    rm -f "$STATE/items.json"
  fi
  rm -rf "$BACKUP"
  refresh
  echo "Demo mode OFF. Your real digests and open items are back."
  ;;
*)
  echo "usage: $0 on|off" >&2
  exit 1
  ;;
esac
