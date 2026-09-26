#!/usr/bin/env python3
"""Open action items that survive across runs.

    python3 triage.py --ingest digests/2026-09-25-1700.md
    python3 triage.py --list
    python3 triage.py --done icloud:88827
    python3 triage.py --json

A digest file is a snapshot of one run: an item raised at 08:07 is invisible
after 13:07 unless you go and open the old file. That makes "did I deal with
this?" unanswerable. This keeps a list of open items instead, keyed by the
account and UID that the draft handle already carries, so an item stays in
front of you until you close it.

Closing is per item, not per run -- the opposite of "mark all caught up",
which only ever meant "I have looked at this digest".
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HOME_DIR = Path.home() / ".mail-digest"
ITEMS_FILE = HOME_DIR / "items.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load() -> dict:
    if ITEMS_FILE.exists():
        try:
            return json.loads(ITEMS_FILE.read_text())
        except json.JSONDecodeError:
            return {"items": {}}
    return {"items": {}}


def save(data: dict) -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    ITEMS_FILE.write_text(json.dumps(data, indent=2) + "\n")


def parse_digest(text: str) -> list[dict]:
    """Pull needs-action items out of a rendered digest.

    Only items carrying a draft handle are tracked: that handle is the one
    stable identity a message has here, and an item we cannot identify is one
    we could never reliably close.
    """
    items: list[dict] = []
    inbox = role = ""
    bucket = ""
    who = subject = ""

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("### "):
            heading = line[4:]
            left, _, right = heading.partition("—")
            inbox, role = left.strip(), right.strip()
            bucket = ""
            who = subject = ""
            continue
        if re.fullmatch(r"\*\*Needs action\*\*", line):
            bucket = "act"; continue
        if re.fullmatch(r"\*\*Worth knowing\*\*", line):
            bucket = "fyi"; continue
        m = re.fullmatch(r"\*\*([^*]+)\*\*(?:\s*\((.+)\))?", line)
        if m:
            who = m.group(1).strip()
            if m.group(2):
                who = f"{who} ({m.group(2).strip()})"
            subject = ""
            continue
        m = re.search(r"\*\*Subject:\*\*\s*(.+)", line)
        if m:
            subject = m.group(1).strip()
            continue
        m = re.search(r"draft:\s*--account\s+(\S+)\s+--uid\s+(\d+)", line)
        # The handle itself is the signal: the prompt only permits it on
        # needs-action items. Requiring an explicit "**Needs action**" header
        # dropped a whole digest silently when the model omitted the header --
        # which it does when there is nothing worth-knowing to separate from.
        # Skip only when we positively know we are in the other bucket.
        if m and bucket != "fyi":
            items.append({
                "id": f"{m.group(1)}:{m.group(2)}",
                "account": m.group(1),
                "uid": int(m.group(2)),
                "subject": subject,
                "who": who,
                "inbox": inbox,
                "role": role,
            })
            who = subject = ""
    return items


def ingest(path: Path) -> tuple[int, int]:
    """Add anything new. Re-ingesting a digest must not reopen closed items."""
    data = load()
    store = data.setdefault("items", {})
    added = skipped = 0
    for item in parse_digest(path.read_text()):
        if item["id"] in store:
            skipped += 1
            continue
        store[item["id"]] = {
            **item,
            "state": "open",
            "first_seen": now(),
            "digest": path.stem,
            "closed_at": None,
        }
        added += 1
    save(data)
    return added, skipped


def open_items(data: dict | None = None) -> list[dict]:
    data = data or load()
    items = [i for i in data.get("items", {}).values() if i.get("state") == "open"]
    # Oldest first: something raised three days ago matters more than this run's.
    return sorted(items, key=lambda i: i.get("first_seen") or "")


def close(item_id: str) -> str:
    data = load()
    item = data.get("items", {}).get(item_id)
    if not item:
        return f"No item {item_id}."
    if item.get("state") == "done":
        return f"{item_id} was already done."
    item["state"] = "done"
    item["closed_at"] = now()
    save(data)
    return f"Closed {item_id} — {item.get('subject') or item.get('who') or ''}".strip()


def reopen(item_id: str) -> str:
    data = load()
    item = data.get("items", {}).get(item_id)
    if not item:
        return f"No item {item_id}."
    item["state"] = "open"
    item["closed_at"] = None
    save(data)
    return f"Reopened {item_id}."


def main() -> int:
    p = argparse.ArgumentParser(description="Track open action items across runs.")
    p.add_argument("--ingest", type=Path, help="add needs-action items from a digest file")
    p.add_argument("--list", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--tsv", action="store_true", help="id, inbox, subject -- for the menu bar")
    p.add_argument("--done", metavar="ID")
    p.add_argument("--reopen", metavar="ID")
    p.add_argument("--all", action="store_true", help="with --list, include closed items")
    args = p.parse_args()

    if args.ingest:
        added, skipped = ingest(args.ingest)
        print(f"{added} new, {skipped} already tracked.")
        return 0
    if args.done:
        print(close(args.done)); return 0
    if args.reopen:
        print(reopen(args.reopen)); return 0
    if args.json:
        print(json.dumps(open_items(), indent=2)); return 0
    if args.tsv:
        for i in open_items():
            label = (i.get("subject") or i.get("who") or i["id"]).replace("\t", " ")
            print("\t".join([i["id"], i.get("inbox", ""), label]))
        return 0

    data = load()
    rows = list(data.get("items", {}).values()) if args.all else open_items(data)
    if not rows:
        print("Nothing open.")
        return 0
    for i in rows:
        mark = "·" if i.get("state") == "open" else "✓"
        print(f"  {mark} {i['id']:<22} {i.get('inbox',''):<28} {(i.get('subject') or i.get('who') or '')[:52]}")
    print(f"\n{len(open_items(data))} open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
