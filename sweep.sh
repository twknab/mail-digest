#!/bin/bash
# Work backwards through the mail the scheduled job will never see.
#
#   ./sweep.sh          # one batch of 25 per account
#   ./sweep.sh 40       # a bigger batch
#
# The first real run set a baseline at whatever the newest UID was, so the
# schedule only ever looks forward. Everything older is unreachable by it --
# thousands of messages, including things that still matter. This walks back
# from that baseline in batches, newest first, and feeds anything actionable
# into the same open-items list the digest uses.
#
# It never moves the forward baseline, so scheduled runs keep working normally.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATCH="${1:-25}"
STATE="$HOME/.mail-digest"
CURSORS="$STATE/sweep.json"
BATCHFILE="$STATE/sweep-batch.json"
LOG="$DIR/digest.log"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
CLAUDE="$(command -v claude || true)"
[ -n "$CLAUDE" ] || { echo "claude not on PATH"; exit 127; }

mkdir -p "$STATE" "$DIR/digests"
OUTFILE="$DIR/digests/sweep-$(date +%Y-%m-%d-%H%M).md"

advance_cursor() {
  python3 - "$CURSORS" "$1" "$2" <<'EOF'
import json, sys
from pathlib import Path
p, name, low = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
cur = json.loads(p.read_text()) if p.exists() else {}
cur[name] = max(1, low)
p.write_text(json.dumps(cur, indent=2) + "\n")
EOF
}

accounts="$(python3 -c "
import json
from pathlib import Path
print(' '.join(a['name'] for a in json.loads(Path('$DIR/accounts.json').read_text())['accounts']))")"

for account in $accounts; do
  cursor="$(python3 - "$account" "$CURSORS" "$STATE/state.json" <<'EOF'
import json, sys
from pathlib import Path
name, cursors, state = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
cur = json.loads(cursors.read_text()) if cursors.exists() else {}
if name in cur:
    print(cur[name])
else:
    st = json.loads(state.read_text()) if state.exists() else {}
    print(st.get(f"{name}:INBOX", {}).get("last_uid", 0))
EOF
)"

  if [ "${cursor:-0}" -le 1 ]; then
    echo "  $account: fully swept."
    continue
  fi

  echo "  $account: reading $BATCH below uid $cursor…"
  python3 "$DIR/mail_digest.py" --account "$account" --no-save \
    --before-uid "$cursor" --max "$BATCH" >"$BATCHFILE" 2>/dev/null
  if [ ! -s "$BATCHFILE" ]; then echo "    (no output)"; continue; fi

  # Read the batch from the file rather than interpolating it into a command:
  # mail is full of quotes and is attacker-influenced text.
  read -r lowest kept <<<"$(python3 - "$BATCHFILE" "$cursor" "$BATCH" <<'EOF'
import json, sys
from pathlib import Path
d = json.loads(Path(sys.argv[1]).read_text())
cursor, batch = int(sys.argv[2]), int(sys.argv[3])
uids = [m["uid"] for m in d.get("messages", [])]
# Advance past everything SCANNED, not just what survived the bulk filter --
# otherwise a batch of pure newsletters would loop on the same messages forever.
low = d["accounts"][0].get("lowest_scanned") or (min(uids) if uids else cursor - batch)
print(low, len(uids))
EOF
)"

  echo "    $kept message(s) survived the bulk filter"

  if [ "${kept:-0}" -gt 0 ]; then
    PROMPT="$(sed "s|~/mail-digest|$DIR|g" "$DIR/prompt-digest.md")

This is a BACKLOG SWEEP, not a live run. Do NOT run mail_digest.py. The JSON for
this batch is already at $BATCHFILE -- read that file and triage it exactly as
described above. This is older mail, so be stricter: anything already overtaken
by events is a Drop."
    BEFORE="$(wc -c <"$OUTFILE" 2>/dev/null || echo 0)"
    # Read(//abs/path) -- a permission rule starting with a single slash is
    # read as project-relative, so an absolute path outside the project needs
    # the extra one. $BATCHFILE already begins with /.
    "$CLAUDE" -p "$PROMPT" --allowedTools "Read(/$BATCHFILE)" \
      >>"$OUTFILE" 2>>"$LOG"
    AFTER="$(wc -c <"$OUTFILE" 2>/dev/null || echo 0)"

    # Only advance past messages that were genuinely triaged. If the model
    # could not read the batch, or went off-script, the cursor must stay put --
    # otherwise these messages are skipped forever and nobody ever finds out.
    if [ "$AFTER" -le "$BEFORE" ] || ! tail -c "$((AFTER - BEFORE))" "$OUTFILE" | grep -qE '^ACTION_ITEMS:[[:space:]]*[0-9]+'; then
      echo "    NOT triaged (no item count) — cursor left at $cursor" | tee -a "$LOG"
      continue
    fi
  fi

  advance_cursor "$account" "$lowest"
  echo "    cursor now $lowest"
done

if [ -s "$OUTFILE" ]; then
  python3 "$DIR/triage.py" --ingest "$OUTFILE"
  echo "$(date -Iseconds) sweep -> $OUTFILE" >>"$LOG"
  echo "Wrote $OUTFILE"
else
  rm -f "$OUTFILE"
  echo "Nothing actionable in this batch."
fi
