#!/bin/bash
# Installs the launchd schedule. Run after accounts.json exists and a manual
# run has worked -- see SETUP.md. Safe to re-run; it replaces the existing job.
#
# Works from wherever you put this folder; it resolves its own location.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Override with MAIL_DIGEST_LABEL if you run more than one copy.
LABEL="${MAIL_DIGEST_LABEL:-local.mail-digest}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ -f "$DIR/accounts.json" ] || { echo "Missing $DIR/accounts.json — see SETUP.md step 4."; exit 1; }

chmod +x "$DIR/run-digest.sh"
mkdir -p "$HOME/Library/LaunchAgents" "$DIR/digests"

# Render and validate in a temp file BEFORE touching the installed plist. A `>`
# straight onto $PLIST truncates it before sed runs, so a missing or broken
# template would leave a zero-byte plist behind and the next bootstrap would
# fail obscurely against a file that exists.
TEMPLATE="$DIR/launchd.plist.template"
[ -f "$TEMPLATE" ] || { echo "Missing $TEMPLATE"; exit 1; }
TMP_PLIST="$(mktemp -t "$LABEL")"
trap 'rm -f "$TMP_PLIST"' EXIT
sed -e "s|REPLACE_DIR|$DIR|g" -e "s|REPLACE_LABEL|$LABEL|g" "$TEMPLATE" > "$TMP_PLIST"
plutil -lint "$TMP_PLIST" >/dev/null
mv "$TMP_PLIST" "$PLIST"
trap - EXIT

# bootout first so a re-run replaces cleanly rather than erroring.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Installed $LABEL"
echo "  script:   $DIR/run-digest.sh"
echo "  schedule: 08:07, 13:07, 17:07, Monday to Friday"
echo
echo "Fire one now without waiting:"
echo "  launchctl kickstart -k gui/$(id -u)/$LABEL"
echo "Remove it later:"
echo "  launchctl bootout gui/$(id -u)/$LABEL && rm $PLIST"
