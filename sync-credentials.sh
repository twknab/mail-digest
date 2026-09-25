#!/bin/bash
# Copies each account's app password from 1Password into the login Keychain.
#
#   ./sync-credentials.sh              # all accounts
#   ./sync-credentials.sh gmail-work   # just one
#
# Why both stores: 1Password is the source of truth, the Keychain is a delivery
# cache. The 08:07 run happens with nobody there, and `op` wants the desktop app
# unlocked plus a biometric approval it cannot get from launchd -- so the
# schedule reads the Keychain and never talks to 1Password at all. Run this once
# now, and again whenever you rotate a password.
#
# The secret goes 1Password -> this process -> `security` over a pipe. It is
# never written to a file and never appears in argv, so it stays out of `ps`
# and out of your shell history.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$DIR/accounts.json"
ONLY="${1:-}"

command -v op >/dev/null 2>&1 || {
  echo "1Password CLI not found. Install it with:  brew install 1password-cli" >&2
  echo "Then enable Settings -> Developer -> 'Integrate with 1Password CLI'." >&2
  exit 1
}

# Fail early and clearly rather than once per account.
if ! op whoami >/dev/null 2>&1; then
  echo "Not signed in to 1Password. Unlock the desktop app, then run:  eval \$(op signin)" >&2
  exit 1
fi

# name<TAB>user<TAB>service<TAB>secret_ref  -- secret_ref falls back to a
# convention so a plain accounts.json needs no extra field.
ROWS="$(python3 - "$CONFIG" <<'PY'
import json, sys
from pathlib import Path
for a in json.loads(Path(sys.argv[1]).read_text()).get("accounts", []):
    service = a.get("keychain_service") or f"mail-digest-{a['name']}"
    ref = a.get("secret_ref") or f"op://Private/{service}/password"
    print("\t".join([a["name"], a["user"], service, ref]))
PY
)"

FAILED=0
SYNCED=0
while IFS=$'\t' read -r NAME USER SERVICE REF; do
  [ -n "$NAME" ] || continue
  if [ -n "$ONLY" ] && [ "$NAME" != "$ONLY" ]; then continue; fi

  printf '%-16s %s ... ' "$NAME" "$REF"
  if ! SECRET="$(op read "$REF" 2>/dev/null)" || [ -z "$SECRET" ]; then
    echo "NOT FOUND in 1Password"
    echo "    Create that item, or add a \"secret_ref\" to this account in accounts.json." >&2
    FAILED=$((FAILED + 1))
    continue
  fi

  # -U updates in place so re-running is safe. -T /usr/bin/security is what
  # stops macOS raising an authorisation dialog at 08:07. The value goes twice
  # on stdin because `security -w` asks you to retype it.
  if printf '%s\n%s\n' "$SECRET" "$SECRET" \
       | security add-generic-password -s "$SERVICE" -a "$USER" -T /usr/bin/security -U -w >/dev/null 2>&1; then
    echo "-> Keychain '$SERVICE'"
    SYNCED=$((SYNCED + 1))
  else
    echo "FAILED writing to Keychain"
    FAILED=$((FAILED + 1))
  fi
  unset SECRET
done <<< "$ROWS"

echo
echo "Synced $SYNCED account(s); $FAILED failed."
[ "$FAILED" -eq 0 ] || exit 1
echo "Check a read without moving the saved position:"
echo "  python3 $DIR/mail_digest.py --no-save --since-hours 2"
