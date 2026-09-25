#!/bin/bash
# Adds one mail account: writes the accounts.json entry, then prompts you to
# type its app password straight into the Keychain.
#
#   ./add-account.sh gmail work you@work.com
#
# Provider ids come from providers.json. Prefer setup_server.py -- this script
# exists for scripted or headless setup.
#
# The password is typed at the `security` prompt and goes nowhere else -- not
# into this script's arguments, not into a file, not into shell history.
#
# iCloud aliases need no entry of their own: every alias delivers into the same
# INBOX as the primary address, so one iCloud account already covers them all.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$DIR/accounts.json"

PROVIDER="${1:-}"; LABEL="${2:-}"; EMAIL="${3:-}"
if [ -z "$PROVIDER" ] || [ -z "$EMAIL" ]; then
  echo "usage: $0 <provider-id> <label|\"\"> <email>   (ids: $(python3 -c 'import json;print(\" \".join(p["id"] for p in json.load(open("providers.json"))["providers"]))'))" >&2
  exit 1
fi

NAME="$PROVIDER"
[ -n "$LABEL" ] && NAME="$PROVIDER-$LABEL"
SERVICE="mail-digest-$NAME"

# Write the config entry first. If the name collides we want to fail before
# asking anyone to type a password.
python3 - "$CONFIG" "$NAME" "$PROVIDER" "$EMAIL" "$SERVICE" "$DIR/providers.json" <<'PY'
import json, sys
from pathlib import Path

path, name, provider, email, service = Path(sys.argv[1]), *sys.argv[2:6]
data = json.loads(path.read_text()) if path.exists() else {"accounts": []}
accounts = data.setdefault("accounts", [])

if any(a.get("name") == name for a in accounts):
    sys.exit(f"An account named '{name}' already exists in {path}. "
             "Pick a different label, or edit the existing entry.")
if any(a.get("user") == email for a in accounts):
    sys.exit(f"{email} is already configured in {path}.")

providers = json.loads(Path(sys.argv[6]).read_text())["providers"]
matches = [p for p in providers if p["id"] == provider]
if not matches:
    sys.exit(f"Unknown provider '{provider}'. Known: " + ", ".join(p["id"] for p in providers))
presets = matches[0]

accounts.append({
    "name": name, "host": presets["host"], "port": presets.get("port", 993), "user": email,
    "mailbox": "INBOX", "sent_mailbox": presets["sent_mailbox"],
    "drafts_mailbox": presets["drafts_mailbox"],
    "smtp_host": presets["smtp_host"], "smtp_port": presets.get("smtp_port", 587),
    "keychain_service": service,
})
path.write_text(json.dumps(data, indent=2) + "\n")
print(f"Added '{name}' ({email}) to {path.name}")
PY

# -T /usr/bin/security is what lets the 08:07 run read this without macOS
# raising an authorisation dialog nobody is there to dismiss.
if security find-generic-password -s "$SERVICE" -a "$EMAIL" >/dev/null 2>&1; then
  echo "Keychain item '$SERVICE' already exists — leaving it alone."
else
  echo
  echo "Now paste the app-specific password for $EMAIL."
  echo "(It will not echo, and it is not stored anywhere but the Keychain.)"
  security add-generic-password -s "$SERVICE" -a "$EMAIL" -T /usr/bin/security -w
  echo "Stored in Keychain as '$SERVICE'."
fi

echo
echo "Verify it, without moving the saved position:"
echo "  python3 $DIR/mail_digest.py --account $NAME --no-save --since-hours 2"
