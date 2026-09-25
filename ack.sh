#!/bin/bash
# Mark the newest digest as seen, so the menu bar dot goes green.
#
# Acknowledgement is per-digest, not a global "quiet" switch: the next run
# writes a new file, so anything that arrives after this goes orange again.
# Dismissing can never hide new mail.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="$HOME/.mail-digest"
latest="$(ls -t "$DIR/digests"/*.md 2>/dev/null | head -1)"

mkdir -p "$STATE"
if [ -z "$latest" ]; then
  echo "No digest to acknowledge."
  exit 0
fi

basename "$latest" .md > "$STATE/acknowledged"
echo "Marked $(basename "$latest" .md) as seen."
