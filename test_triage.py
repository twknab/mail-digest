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

print("a digest with no bucket headers -- the model omits them when there is nothing FYI")
NO_HEADERS = """# Mail digest

### work@example.com — business

**Someone** (a@b.example)
- **Subject:** Renewal needs information
- draft: --account aliased --uid 7001

### me@example.com — personal

**Another** (c@d.example)
- **Subject:** Account alert
- draft: --account aliased --uid 7002

ACTION_ITEMS: 2
"""
got = tr.parse_digest(NO_HEADERS)
check("items are still captured", [i["uid"] for i in got], [7001, 7002])
check("inbox still attributed", got[0]["inbox"], "work@example.com")
check("worth-knowing is still excluded when the header IS present",
      [i["uid"] for i in tr.parse_digest(
          "### a@b.com — personal\n\n**Worth knowing**\n\n**X** (x@y.z)\n"
          "- **Subject:** fyi\n- draft: --account a --uid 9\n")], [])


print("lead-line shapes the model actually produces")
# Every one of these appeared in a real digest. The first three used to yield
# an item with no sender and no subject, which surfaced as its own id.
EMDASH = """### shop@example.com — shopping

**Needs action**

**Guardian Water & Power** — *Your Guardian Bill is Ready*
- **What it says:** Your bill is $93.88, due 11/07.
- draft: --account aliased --uid 89464
"""
got = tr.parse_digest(EMDASH)
check("em dash + emphasis: sender", got[0]["who"], "Guardian Water & Power")
check("em dash + emphasis: subject", got[0]["subject"], "Your Guardian Bill is Ready")

PLAIN_DASH = "**Public Storage** — payment failure and AutoPay shut off\n- draft: --account aliased --uid 89322\n"
got = tr.parse_digest(PLAIN_DASH)
check("em dash, no emphasis: subject", got[0]["subject"],
      "payment failure and AutoPay shut off")

PARENS = "**Dana Ruiz** (dana@client.example)\n- **Subject:** Q3 SOW\n- draft: --account aliased --uid 1\n"
got = tr.parse_digest(PARENS)
check("parenthesised address still works", got[0]["who"], "Dana Ruiz (dana@client.example)")
check("explicit Subject line still wins", got[0]["subject"], "Q3 SOW")

BARE = "**Someone**\n- **Subject:** Explicit subject\n- draft: --account aliased --uid 2\n"
check("bare name + explicit subject", tr.parse_digest(BARE)[0]["subject"], "Explicit subject")

print("one item, several handles")
# The model merges messages sent minutes apart. Both handles are the same
# sender and subject; clearing them after the first left the second blank.
TWO = """**Public Storage** — payment failure and AutoPay shut off
  - draft: --account aliased --uid 89322
  - draft: --account aliased --uid 89323
"""
got = tr.parse_digest(TWO)
check("both handles captured", [i["uid"] for i in got], [89322, 89323])
check("second keeps the sender", got[1]["who"], "Public Storage")
check("second keeps the subject", got[1]["subject"],
      "payment failure and AutoPay shut off")

print("a new lead line resets the previous one")
RESET = """**First** — subject one
- draft: --account aliased --uid 11

**Second** — subject two
- draft: --account aliased --uid 22
"""
got = tr.parse_digest(RESET)
check("two separate items", [i["subject"] for i in got], ["subject one", "subject two"])
check("second does not inherit the first", got[1]["who"], "Second")


print()
print(f"{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
