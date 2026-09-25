#!/usr/bin/env python3
"""Offline checks for reply drafting. No network, no mailbox, no Keychain."""

import email
import email.policy

import mail_reply as mr

PASSED = FAILED = 0


def check(label, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL {label}\n    got:  {got!r}\n    want: {want!r}")


ALIASED = {
    "name": "aliased", "user": "me@example.com", "mailbox": "INBOX",
    "drafts_mailbox": "Drafts",
    "alias_roles": {
        "me@example.com": "personal",
        "family@example.com": "personal",
        "work@example.com": "business",
        "shop@example.com": "shopping",
    },
}
SOLO = {"name": "solo", "user": "solo@example.net",
         "drafts_mailbox": "Drafts"}


def msg(raw):
    return email.message_from_string(raw, policy=email.policy.default)


BUSINESS = msg(
    "From: Dana Ruiz <dana@client.example>\n"
    "To: work@example.com\n"
    "Subject: Q3 statement of work\n"
    "Date: Tue, 23 Sep 2026 09:14:02 -0700\n"
    "Message-ID: <abc123@client.example>\n"
    "\n"
    "Can you approve the SOW by Friday?\n"
)

print("from_address_for")
check("replies from the alias it was sent to", mr.from_address_for(BUSINESS, ALIASED),
      "work@example.com")
check("shopping alias", mr.from_address_for(msg("To: shop@example.com\n\nx\n"), ALIASED),
      "shop@example.com")
check("primary when addressed to primary",
      mr.from_address_for(msg("To: me@example.com\n\nx\n"), ALIASED), "me@example.com")
check("case-insensitive alias match",
      mr.from_address_for(msg("To: WORK@Example.com\n\nx\n"), ALIASED), "work@example.com")
check("Delivered-To beats To (bcc'd mail)",
      mr.from_address_for(msg("Delivered-To: family@example.com\nTo: list@x.example\n\nx\n"), ALIASED),
      "family@example.com")
check("never replies from a stranger's address",
      mr.from_address_for(msg("To: someone@elsewhere.example\n\nx\n"), ALIASED),
      "me@example.com")
check("single-address account uses its own login",
      mr.from_address_for(msg("To: whoever@x.example\n\nx\n"), SOLO), "solo@example.net")
check("account_addresses collects primary + aliases",
      sorted(mr.account_addresses(ALIASED)),
      ["family@example.com", "me@example.com", "shop@example.com", "work@example.com"])

print("reply_subject")
check("adds Re:", mr.reply_subject("Q3 statement of work"), "Re: Q3 statement of work")
check("does not double Re:", mr.reply_subject("Re: Q3 budget"), "Re: Q3 budget")
check("case-insensitive existing Re:", mr.reply_subject("RE: shipping"), "RE: shipping")
check("empty subject", mr.reply_subject(""), "Re:")
check("None subject", mr.reply_subject(None), "Re:")

print("reply_recipient")
check("uses From when no Reply-To", mr.reply_recipient(BUSINESS), "dana@client.example")
check("Reply-To wins over From",
      mr.reply_recipient(msg("From: bot@x.example\nReply-To: human@x.example\n\nx\n")),
      "human@x.example")

print("build_reply")
r = mr.build_reply(BUSINESS, ALIASED, "Approved — sending signature today.")
check("From is the alias", r["From"], "work@example.com")
check("To is the sender", r["To"], "dana@client.example")
check("subject prefixed", r["Subject"], "Re: Q3 statement of work")
check("In-Reply-To set", r["In-Reply-To"], "<abc123@client.example>")
check("References carries the chain", r["References"], "<abc123@client.example>")
check("body present", "Approved — sending signature today." in r.get_content(), True)
check("original is quoted", "> Can you approve the SOW by Friday?" in r.get_content(), True)
check("attribution line", "Dana Ruiz wrote:" in r.get_content(), True)

chained = msg(
    "From: a@x.example\nTo: work@example.com\nSubject: Re: thread\n"
    "Message-ID: <third@x.example>\nReferences: <first@x.example> <second@x.example>\n\nhi\n"
)
check("References appends to existing chain",
      mr.build_reply(chained, ALIASED, "ok")["References"],
      "<first@x.example> <second@x.example> <third@x.example>")

no_id = msg("From: a@x.example\nTo: work@example.com\nSubject: no id\n\nhi\n")
check("absent Message-ID means no In-Reply-To rather than a bogus one",
      mr.build_reply(no_id, ALIASED, "ok").get("In-Reply-To"), None)

print("safety")
check("module exposes no SMTP capability", hasattr(mr, "smtplib"), False)
check("no send function exists", any(n for n in dir(mr) if "send" in n.lower()), False)

print()
print(f"{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
