#!/usr/bin/env python3
"""Prove the reader does not mark mail as read.

    python3 check_readonly.py            # snapshot unread counts
    python3 check_readonly.py --compare before.json

SETUP.md asks you to note unread counts by hand before and after a run. Doing
it over IMAP instead catches a single message flipping read, which eyeballing
a mailbox does not.

STATUS does not open the mailbox, so this measurement cannot itself change
what it measures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import mail_digest as md


def counts_for(account: dict) -> dict:
    mailbox = account.get("mailbox", "INBOX")
    try:
        conn = md.connect(account)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    try:
        typ, data = conn.status(f'"{mailbox}"', "(MESSAGES UNSEEN)")
        if typ != "OK" or not data:
            return {"error": "STATUS refused"}
        blob = data[0].decode() if isinstance(data[0], bytes) else str(data[0])
        found = {k.lower(): int(v) for k, v in re.findall(r"(MESSAGES|UNSEEN)\s+(\d+)", blob)}
        return {"messages": found.get("messages"), "unseen": found.get("unseen")}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def snapshot(accounts: list[dict]) -> dict:
    return {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "accounts": {a["name"]: counts_for(a) for a in accounts},
    }


def main() -> int:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="Snapshot or compare unread counts.")
    p.add_argument("--config", type=Path, default=here / "accounts.json")
    p.add_argument("--compare", type=Path, help="an earlier snapshot to diff against")
    args = p.parse_args()

    accounts = md.load_accounts(args.config)
    now = snapshot(accounts)

    if not args.compare:
        print(json.dumps(now, indent=2))
        return 0

    before = json.loads(args.compare.read_text())
    changed = False
    print(f"{'account':<24} {'unread before':>14} {'after':>8}   verdict")
    for name, after in now["accounts"].items():
        was = before["accounts"].get(name, {})
        if after.get("error") or was.get("error"):
            print(f"{name:<24} {'?':>14} {'?':>8}   ERROR {after.get('error') or was.get('error')}")
            changed = True
            continue
        b, a = was.get("unseen"), after.get("unseen")
        ok = b == a
        changed = changed or not ok
        print(f"{name:<24} {b:>14} {a:>8}   {'unchanged' if ok else 'CHANGED — mail was marked read'}")

    print()
    if changed:
        print("FAIL: something altered read state. Do not schedule this.", file=sys.stderr)
        return 1
    print("PASS: every unread count is identical. The reader left your mail alone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
