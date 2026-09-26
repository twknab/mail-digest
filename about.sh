#!/bin/bash
# Native About pane.
#
# A real macOS alert rather than a launched HTML page: an About box is a system
# affordance and people expect a panel, not a browser tab opening behind their
# other windows.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

COUNT="$(python3 "$DIR/triage.py" --tsv 2>/dev/null | grep -c . || echo 0)"
LAST="$(grep -E 'action items' "$DIR/digest.log" 2>/dev/null | tail -1 | cut -d' ' -f1 | cut -dT -f1,2 | tr 'T' ' ' | cut -c1-16)"
ACCOUNTS="$(python3 -c "
import json
from pathlib import Path
try:
    print(len(json.loads(Path('$DIR/accounts.json').read_text())['accounts']))
except Exception:
    print('?')
" 2>/dev/null)"

MESSAGE="Three weekday digests of the mail that actually needs you.

Runs entirely on this Mac. Nothing is uploaded, and no password is written to a file.

Read-only by construction — mailboxes open readonly and every fetch uses BODY.PEEK, so a run never marks mail as read.

Replies are drafted into your Drafts folder and never sent; the drafting module holds no send capability at all.

────────────
$ACCOUNTS accounts · $COUNT open item(s)
Last run: ${LAST:-never}"

CHOICE="$(osascript <<EOF 2>/dev/null
display alert "Mail Digest" message "$MESSAGE" buttons {"timknab.dev", "Open full page", "OK"} default button "OK"
EOF
)"

case "$CHOICE" in
  *"timknab.dev"*)   open "https://timknab.dev" ;;
  *"Open full page"*) open "$HOME/.mail-digest/view/about.html" ;;
esac
