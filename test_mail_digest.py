#!/usr/bin/env python3
"""Tests for the parts of the reader that do not need a mailbox.

Deliberately dependency-free (no pytest) so it runs on a stock macOS python3.
Run:  python3 test_mail_digest.py
"""

import email
import email.policy
from datetime import datetime, timedelta, timezone

import mail_digest as md

PASSED = FAILED = 0


def check(label, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL {label}\n       got:  {got!r}\n       want: {want!r}")


def msg(raw: str):
    return email.message_from_string(raw, policy=email.policy.default)


NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)


# --- unsubscribe extraction (RFC 2369 / RFC 8058) -------------------------
print("unsubscribe_info")

one_click = msg(
    "From: News <news@shop.example>\r\n"
    "Subject: Sale\r\n"
    "List-Unsubscribe: <https://shop.example/u/abc>, <mailto:u@shop.example>\r\n"
    "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n\r\nbody\r\n")
u = md.unsubscribe_info(one_click)
check("one-click http", u["http"], "https://shop.example/u/abc")
check("one-click mailto", u["mailto"], "mailto:u@shop.example")
check("one-click flag", u["one_click"], True)

http_only = msg("From: a@b.example\r\nList-Unsubscribe: <https://b.example/stop>\r\n\r\nx\r\n")
check("http only -> not one-click", md.unsubscribe_info(http_only)["one_click"], False)
check("http only url", md.unsubscribe_info(http_only)["http"], "https://b.example/stop")

mailto_only = msg("From: a@b.example\r\nList-Unsubscribe: <mailto:off@b.example>\r\n\r\nx\r\n")
check("mailto only http", md.unsubscribe_info(mailto_only)["http"], None)
check("mailto only mailto", md.unsubscribe_info(mailto_only)["mailto"], "mailto:off@b.example")

# A Post header without a usable http target must not claim one-click.
liar = msg("From: a@b.example\r\nList-Unsubscribe: <mailto:off@b.example>\r\n"
           "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n\r\nx\r\n")
check("post header but no url", md.unsubscribe_info(liar)["one_click"], False)

plain = msg("From: Real Person <p@friend.example>\r\nSubject: lunch?\r\n\r\nx\r\n")
check("no unsubscribe", md.unsubscribe_info(plain), {"http": None, "mailto": None, "one_click": False})


# --- bulk detection -------------------------------------------------------
print("is_bulk")
check("List-Unsubscribe => bulk", md.is_bulk(one_click, []), True)
check("personal mail => not bulk", md.is_bulk(plain, []), False)
check("Gmail promo label => bulk", md.is_bulk(plain, ["CATEGORY_PROMOTIONS"]), True)
check("Gmail Important label => not bulk", md.is_bulk(plain, ["Important"]), False)
check("Precedence: bulk => bulk",
      md.is_bulk(msg("From: a@b.example\r\nPrecedence: bulk\r\n\r\nx\r\n"), []), True)
check("Auto-Submitted => bulk",
      md.is_bulk(msg("From: a@b.example\r\nAuto-Submitted: auto-generated\r\n\r\nx\r\n"), []), True)
check("List-Id => bulk",
      md.is_bulk(msg("From: a@b.example\r\nList-Id: <l.b.example>\r\n\r\nx\r\n"), []), True)


# --- body snippet ---------------------------------------------------------
print("body_snippet")
check("plain text collapsed",
      md.body_snippet(msg("From: a@b.example\r\n\r\nHello   there\r\n\r\nworld\r\n")),
      "Hello there world")

html = msg("From: a@b.example\r\nContent-Type: text/html\r\n\r\n"
           "<style>p{color:red}</style><p>Hi <b>there</b></p>\r\n")
check("html stripped", md.body_snippet(html), "Hi there")

long_msg = msg("From: a@b.example\r\n\r\n" + ("word " * 400))
snip = md.body_snippet(long_msg)
check("truncated to cap", len(snip) <= md.SNIPPET_CHARS + 1, True)
check("truncation marked", snip.endswith("…"), True)


# --- address helpers ------------------------------------------------------
print("addr_of / domain_of")
check("display name stripped", md.addr_of("Real Person <P@Friend.Example>"), "p@friend.example")
check("bare address", md.addr_of("x@y.example"), "x@y.example")
check("garbage", md.addr_of("not an address"), "")
check("domain", md.domain_of("p@friend.example"), "friend.example")


# --- FETCH metadata parsing ----------------------------------------------
print("parse_meta")
gmail_resp = [(b'1 (UID 42 FLAGS (\\Seen \\Flagged) X-GM-LABELS ("\\\\Important" "CATEGORY_PROMOTIONS") BODY[] {5}',
               b"hello"), b")"]
flags, labels = md.parse_meta(gmail_resp)
check("flags parsed", sorted(flags), ["Flagged", "Seen"])
check("labels parsed", labels, ["Important", "CATEGORY_PROMOTIONS"])

plain_resp = [(b'1 (UID 7 FLAGS () BODY[] {5}', b"hello"), b")"]
flags2, labels2 = md.parse_meta(plain_resp)
check("no flags", flags2, [])
check("no labels", labels2, [])

# Label text must never leak into flags -- \\Important would look like a flag.
check("label not read as flag", "Important" in flags, False)


# --- record building ------------------------------------------------------
print("build_record")
rec = md.build_record(9, msg(
    "From: Boss <boss@work.example>\r\nSubject: Please review the deck by Friday\r\n"
    "Date: Fri, 28 Aug 2026 10:00:00 +0000\r\n\r\nNeeds your approval before the deadline.\r\n"
), ["Flagged"], [], snippet=True)
check("sender addr", rec["from_addr"], "boss@work.example")
check("flagged", rec["flagged"], True)
check("unread (no \\Seen)", rec["unread"], True)
check("action words found", rec["action_words"], ["approval", "deadline", "needs your", "review"])
check("not bulk", rec["bulk"], False)


# --- sender classification -----------------------------------------------
print("classify_sender")

def entry(**kw):
    base = {"address": "news@shop.example", "display": "News", "domain": "shop.example",
            "accounts": ["gmail"], "count": 12, "flagged_count": 0, "categories": set(),
            "unsubscribe": {"http": None, "mailto": None, "one_click": False}}
    base.update(kw)
    return base

e = md.classify_sender(entry(unsubscribe={"http": "https://s/u", "mailto": None, "one_click": True}),
                       {}, NOW, set())
check("one-click recommended", e["recommendation"], "one_click")

e = md.classify_sender(entry(unsubscribe={"http": None, "mailto": "mailto:u@s", "one_click": False}),
                       {}, NOW, set())
check("mailto recommended", e["recommendation"], "mailto")

e = md.classify_sender(entry(unsubscribe={"http": "https://s/u", "mailto": None, "one_click": False}),
                       {}, NOW, set())
check("link needs a human", e["recommendation"], "manual_link")

e = md.classify_sender(entry(), {}, NOW, set())
check("no unsubscribe => filter", e["recommendation"], "hard_filter")

# Protection must beat volume, by every route.
e = md.classify_sender(entry(count=500, ever_replied=True,
                             unsubscribe={"http": "h", "mailto": None, "one_click": True}),
                       {}, NOW, set())
check("replied => keep", e["recommendation"], "keep")
check("replied => protected", e["protected"], True)

e = md.classify_sender(entry(count=500, flagged_count=1,
                             unsubscribe={"http": "h", "mailto": None, "one_click": True}),
                       {}, NOW, set())
check("flagged => keep", e["recommendation"], "keep")

e = md.classify_sender(entry(count=500,
                             unsubscribe={"http": "h", "mailto": None, "one_click": True}),
                       {}, NOW, {"shop.example"})
check("contact domain => keep", e["recommendation"], "keep")

# The escalation path: unsubscribed, grace period elapsed, still arriving.
stale = {"news@shop.example": {"action": "one_click",
                               "date": (NOW - timedelta(days=30)).isoformat()}}
e = md.classify_sender(entry(), stale, NOW, set())
check("ignored unsubscribe => hard filter", e["recommendation"], "hard_filter")
check("ignored flag set", e["unsubscribe_ignored"], True)

# Inside the grace period it is too early to call it ignored.
fresh = {"news@shop.example": {"action": "one_click",
                               "date": (NOW - timedelta(days=3)).isoformat()}}
e = md.classify_sender(entry(unsubscribe={"http": "h", "mailto": None, "one_click": True}),
                       fresh, NOW, set())
check("within grace => not ignored", e["unsubscribe_ignored"], False)
check("within grace => still one_click", e["recommendation"], "one_click")

# A naive-datetime ledger entry must not crash the run.
naive = {"news@shop.example": {"action": "one_click",
                               "date": "2026-01-01T00:00:00"}}
e = md.classify_sender(entry(), naive, NOW, set())
check("naive datetime handled", e["unsubscribe_ignored"], True)

# Escalation outranks protection: if they ignored an unsubscribe, block them.
e = md.classify_sender(entry(ever_replied=True), stale, NOW, set())
check("ignored beats protected", e["recommendation"], "hard_filter")

# --------------------------------------------------------------------------
# role routing -- Gmail splits by login, iCloud aliases share one INBOX
# --------------------------------------------------------------------------

ALIASED = {
    "name": "aliased", "user": "me@example.com", "role": "personal",
    "alias_roles": {
        "me@example.com": "personal",
        "family@example.com": "personal",
        "work@example.com": "business",
        "shop@example.com": "shopping",
    },
}
SOLO = {"name": "solo", "user": "solo@example.net", "role": "business"}


def msg_to(*headers):
    raw = "From: a@b.com\nSubject: s\n" + "".join(headers) + "\n\nbody\n"
    return email.message_from_string(raw, policy=email.policy.default)


def rec(*headers):
    return {"delivered_to": md.delivered_addrs(msg_to(*headers))}


check("alias routes to business", md.role_for(rec("To: work@example.com\n"), ALIASED), "business")
check("alias routes to shopping", md.role_for(rec("To: shop@example.com\n"), ALIASED), "shopping")
check("primary routes to personal", md.role_for(rec("To: me@example.com\n"), ALIASED), "personal")
check("dotted alias is personal", md.role_for(rec("To: family@example.com\n"), ALIASED), "personal")
check("alias match is case-insensitive", md.role_for(rec("To: WORK@Example.com\n"), ALIASED), "business")
check("unknown recipient falls back to account role",
      md.role_for(rec("To: someone@example.com\n"), ALIASED), "personal")
check("no recipient headers falls back", md.role_for({"delivered_to": []}, ALIASED), "personal")
check("single-address account uses its own role",
      md.role_for(rec("To: solo@example.net\n"), SOLO), "business")
check("account with no role at all defaults personal",
      md.role_for(rec("To: x@y.com\n"), {"name": "n", "user": "x@y.com"}), "personal")

# Delivered-To beats To: mail you were BCC'd on has someone else in To.
check("delivered-to wins over to",
      md.role_for(rec("Delivered-To: shop@example.com\n", "To: someone-else@example.com\n"), ALIASED),
      "shopping")
check("x-original-to is honoured",
      md.role_for(rec("X-Original-To: work@example.com\n", "To: list@example.com\n"), ALIASED),
      "business")
check("cc counts when to does not match",
      md.role_for(rec("To: other@example.com\n", "Cc: work@example.com\n"), ALIASED), "business")
check("delivered_addrs dedupes and lowercases",
      md.delivered_addrs(msg_to("To: A@B.com, a@b.com\n")), ["a@b.com"])


print("identity_for")
check("alias it landed on", md.identity_for({"delivered_to": ["work@example.com"]}, ALIASED),
      "work@example.com")
check("shopping alias", md.identity_for({"delivered_to": ["shop@example.com"]}, ALIASED),
      "shop@example.com")
check("falls back to the login when nothing matches",
      md.identity_for({"delivered_to": ["stranger@elsewhere.example"]}, ALIASED), "me@example.com")
check("falls back with no delivery headers at all",
      md.identity_for({"delivered_to": []}, ALIASED), "me@example.com")
check("first of my addresses wins over a later one",
      md.identity_for({"delivered_to": ["shop@example.com", "work@example.com"]}, ALIASED),
      "shop@example.com")
check("single-address account always reports its login",
      md.identity_for({"delivered_to": ["anything@example.org"]}, SOLO), "solo@example.net")
check("account_addresses includes the login itself",
      "me@example.com" in md.account_addresses(ALIASED), True)


print()
print(f"{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
