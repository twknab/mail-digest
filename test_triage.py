#!/usr/bin/env python3
"""Checks for open-item tracking. Redirects storage to a temp file."""

import json
import tempfile
from pathlib import Path

import triage as tr

PASSED = FAILED = 0


def check(label, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL {label}\n    got:  {got!r}\n    want: {want!r}")


TMP = Path(tempfile.mkdtemp())
tr.HOME_DIR = TMP
tr.ITEMS_FILE = TMP / "items.json"

DIGEST = """# Mail digest — Friday 25 September 2026, 17:07

### work@example.com — business

**Needs action**

**Dana Ruiz** (dana@client.example)
- **Subject:** Q3 statement of work
- **The ask:** Approve by Friday.
- draft: --account aliased --uid 4821

**Worth knowing**

**Newsletter** (news@example.org)
- **Subject:** Weekly roundup
- draft: --account aliased --uid 4822

### shop@example.com — shopping

**Needs action**

**Utilities** (no-reply@example.gov)
- **Subject:** Payment Rejected
- draft: --account aliased --uid 991

ACTION_ITEMS: 2
"""

print("parse_digest")
items = tr.parse_digest(DIGEST)
check("only needs-action items are tracked", len(items), 2)
check("worth-knowing is excluded", [i["uid"] for i in items], [4821, 991])
check("id is account:uid", items[0]["id"], "aliased:4821")
check("subject captured", items[0]["subject"], "Q3 statement of work")
check("sender captured", items[0]["who"], "Dana Ruiz (dana@client.example)")
check("inbox from the section heading", items[0]["inbox"], "work@example.com")
check("role from the section heading", items[0]["role"], "business")
check("second section attributed correctly", items[1]["inbox"], "shop@example.com")
check("an item with no draft handle is skipped",
      len(tr.parse_digest("### a@b.com — personal\n\n**Needs action**\n\n**X**\n- **Subject:** no handle\n")), 0)

print("ingest and close")
src = TMP / "2026-09-25-1700.md"
src.write_text(DIGEST)
check("first ingest adds both", tr.ingest(src), (2, 0))
check("re-ingest adds nothing", tr.ingest(src), (0, 2))
check("both open", len(tr.open_items()), 2)

check("closing reports the subject",
      tr.close("aliased:991").startswith("Closed aliased:991"), True)
check("one left open", len(tr.open_items()), 1)
check("closing twice is refused, not silent",
      tr.close("aliased:991"), "aliased:991 was already done.")
check("unknown id", tr.close("nope:1"), "No item nope:1.")

print("a closed item must not come back")
check("re-ingesting the same digest does not reopen it", tr.ingest(src), (0, 2))
check("still closed", len(tr.open_items()), 1)
check("reopen works when you want it", tr.reopen("aliased:991"), "Reopened aliased:991.")
check("open again", len(tr.open_items()), 2)

print("ordering")
check("oldest first, so old items do not sink",
      tr.open_items()[0]["id"], "aliased:4821")

print("storage")
check("state persists to disk",
      json.loads(tr.ITEMS_FILE.read_text())["items"]["aliased:4821"]["state"], "open")
check("corrupt store does not crash", (tr.ITEMS_FILE.write_text("{ broken"), tr.load())[1],
      {"items": {}})

print()
print(f"{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
