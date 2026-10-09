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
    urgency = ""

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
        # The lead line of an item. The model writes it several ways and all of
        # them are reasonable readings of the prompt:
        #   **Sender**
        #   **Sender** (addr@example.com)
        #   **Sender** — Subject text
        #   **Sender** — *Subject text*
        # Requiring the first two dropped the sender AND the subject for the
        # rest, which is how items ended up labelled with their own id.
        m = re.match(r"\*\*([^*]+)\*\*\s*(.*)$", line)
        if m:
            who = m.group(1).strip()
            rest = m.group(2).strip()
            subject = ""
            urgency = ""
            if rest.startswith("(") and rest.endswith(")"):
                who = f"{who} ({rest[1:-1].strip()})"
            elif rest:
                # "— Subject", "- Subject", "– Subject", optionally *emphasised*
                rest = re.sub(r"^[\u2014\u2013-]+\s*", "", rest)
                subject = rest.strip("*").strip()
            continue
        m = re.search(r"\*\*Subject:\*\*\s*(.+)", line)
        if m:
            subject = m.group(1).strip()
            continue
        m = re.match(r"-?\s*urgency:\s*(high|medium|low)\b", line, re.I)
        if m:
            urgency = m.group(1).lower()
            continue
        m = re.search(r"draft:\s*--account\s+(\S+)\s+--uid\s+(\d+)", line)
        # NOTE: who/subject are deliberately NOT cleared after a handle. One
        # item can carry several, when the model merges messages sent minutes
        # apart, and every one of them belongs to the same sender and subject.
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
                "urgency": urgency or "medium",
            })
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


def refresh(digests_dir: Path) -> tuple[int, int]:
    """Re-read each item's source digest and fill in missing metadata.

    ingest() deliberately skips ids it already knows, so a parser fix cannot
    reach items captured before it. This repairs them in place without
    touching state: an item you closed stays closed.
    """
    data = load()
    store = data.get("items", {})
    parsed: dict[str, dict] = {}
    for f in sorted(digests_dir.glob("*.md")):
        for item in parse_digest(f.read_text()):
            parsed.setdefault(item["id"], item)

    fixed = missing = 0
    for key, item in store.items():
        if item.get("subject") or item.get("who"):
            continue
        found = parsed.get(key)
        if not found:
            missing += 1
            continue
        item["subject"] = found.get("subject", "")
        item["who"] = found.get("who", "")
        if found.get("inbox"):
            item["inbox"] = found["inbox"]
        fixed += 1
    save(data)
    return fixed, missing


RANK = {"high": 0, "medium": 1, "low": 2}
ESCALATE_AFTER_DAYS = 10


def effective_urgency(item: dict) -> str:
    """The model's judgement, raised a step once an item has sat long enough.

    Something low that has been open a fortnight is no longer low: either it
    matters and is being avoided, or it should be closed. Either way it should
    stop looking the same as what arrived this morning.
    """
    u = (item.get("urgency") or "medium").lower()
    if u not in RANK:
        u = "medium"
    seen = item.get("first_seen")
    if not seen:
        return u
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(seen)).days
    except ValueError:
        return u
    if age >= ESCALATE_AFTER_DAYS and u != "high":
        return "high" if u == "medium" else "medium"
    return u


def open_items(data: dict | None = None) -> list[dict]:
    data = data or load()
    items = [i for i in data.get("items", {}).values() if i.get("state") == "open"]
    # Most urgent first, then oldest: something raised three days ago matters
    # more than this run's, but a failing payment outranks both.
    return sorted(items, key=lambda i: (RANK[effective_urgency(i)], i.get("first_seen") or ""))


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
    p.add_argument("--refresh", action="store_true",
                   help="re-read source digests to fill in missing subjects")
    p.add_argument("--all", action="store_true", help="with --list, include closed items")
    args = p.parse_args()

    if args.ingest:
        added, skipped = ingest(args.ingest)
        print(f"{added} new, {skipped} already tracked.")
        return 0
    if args.refresh:
        fixed, missing = refresh(Path(__file__).resolve().parent / "digests")
        print(f"{fixed} repaired, {missing} with no source digest left.")
        return 0
    if args.done:
        print(close(args.done)); return 0
    if args.reopen:
        print(reopen(args.reopen)); return 0
    if args.json:
        print(json.dumps(open_items(), indent=2)); return 0
    if args.tsv:
        for i in open_items():
            label = (i.get("subject") or i.get("who")
                     or f"(no subject — uid {i['uid']})").replace("\t", " ")
            print("\t".join([i["id"], i.get("inbox", ""), label, effective_urgency(i)]))
        return 0

    data = load()
    rows = list(data.get("items", {}).values()) if args.all else open_items(data)
    if not rows:
        print("Nothing open.")
        return 0
    for i in rows:
        mark = {"high": "!", "medium": "·", "low": " "}.get(effective_urgency(i), "·") \
            if i.get("state") == "open" else "✓"
        label = i.get("subject") or i.get("who") or f"(no subject — uid {i['uid']})"
        print(f"  {mark} {i['id']:<22} {i.get('inbox',''):<28} {label[:52]}")
    print(f"\n{len(open_items(data))} open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
