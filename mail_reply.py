#!/usr/bin/env python3
"""Turn a message that needs an answer into a draft reply.

    python3 mail_reply.py --account work --uid 4821 --body-file reply.txt
    python3 mail_reply.py --account personal --uid 991 --body-file r.txt --append

Dry run unless --append, mirroring junk_actions.py. The only write this tool
can perform is APPEND into a Drafts mailbox: it holds no SMTP capability at
all, so nothing it produces can leave your outbox without you pressing Send.

The inbox is opened readonly=True and read with BODY.PEEK, so drafting a reply
leaves unread counts exactly as reading did.

See SPEC-replies.md for why From is chosen from delivery headers rather than
from the account -- aliases share one INBOX, and replying to work mail
from a personal alias is a real leak.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import imaplib
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr
from pathlib import Path

import mail_digest as md

QUOTE_MAX_LINES = 50


account_addresses = md.account_addresses


def from_address_for(msg, account: dict) -> str:
    """Reply as whichever of my addresses this was actually sent to.

    The same rule that labels a message's inbox in the digest, so a reply can
    never go out from an address other than the one it arrived at.
    """
    return md.identity_for({"delivered_to": md.delivered_addrs(msg)}, account)


def reply_recipient(msg) -> str:
    """Reply-To exists precisely to override From. Honour it."""
    for header in ("reply-to", "from"):
        for _, addr in getaddresses(msg.get_all(header, [])):
            if addr:
                return addr.strip()
    return ""


def reply_subject(original: str) -> str:
    subject = (original or "").strip()
    if not subject:
        return "Re:"
    # Re: Re: Re: is noise, and some clients thread on the literal subject.
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def quoted(msg) -> str:
    """Standard attribution line plus '> ' quoting, truncated."""
    name, addr = parseaddr(md.decode(msg.get("from")))
    who = name or addr or "they"
    when = md.decode(msg.get("date")) or "an earlier message"
    body = md.body_snippet(msg)
    lines = (body or "").splitlines()
    clipped = lines[:QUOTE_MAX_LINES]
    if len(lines) > QUOTE_MAX_LINES:
        clipped.append("... [quoted text trimmed]")
    quote = "\n".join(f"> {line}" for line in clipped)
    return f"On {when}, {who} wrote:\n{quote}\n"


def build_reply(msg, account: dict, body: str) -> EmailMessage:
    reply = EmailMessage()
    from_addr = from_address_for(msg, account)
    reply["From"] = from_addr
    reply["To"] = reply_recipient(msg)
    reply["Subject"] = reply_subject(md.decode(msg.get("subject")))
    reply["Date"] = formatdate(localtime=True)
    reply["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1] or None)

    # Without these the recipient's client opens a new conversation instead of
    # continuing the existing one.
    original_id = (msg.get("message-id") or "").strip()
    if original_id:
        reply["In-Reply-To"] = original_id
        existing = (msg.get("references") or "").split()
        reply["References"] = " ".join(existing + [original_id])

    reply.set_content(f"{body.rstrip()}\n\n{quoted(msg)}")
    return reply


def fetch_original(conn, uid: int):
    typ, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        return None
    return email.message_from_bytes(data[0][1], policy=email.policy.default)


def main() -> int:
    default_config = Path(__file__).resolve().parent / "accounts.json"
    p = argparse.ArgumentParser(description="Draft a reply into the Drafts folder.")
    p.add_argument("--account", required=True, help="account name from accounts.json")
    p.add_argument("--uid", required=True, type=int, help="message UID from the digest")
    p.add_argument("--body-file", type=Path, help="file holding the reply text ('-' for stdin)")
    p.add_argument("--body", help="reply text inline (prefer --body-file)")
    p.add_argument("--config", type=Path, default=default_config)
    p.add_argument("--append", action="store_true",
                   help="actually write the draft. Without this it is a dry run.")
    args = p.parse_args()

    if args.body_file and str(args.body_file) == "-":
        body = sys.stdin.read()
    elif args.body_file:
        body = args.body_file.read_text()
    elif args.body:
        body = args.body
    else:
        md.die("no_body", "Pass --body-file or --body with the reply text.")

    accounts = md.load_accounts(args.config)
    matches = [a for a in accounts if a["name"].lower() == args.account.lower()]
    if not matches:
        md.die("unknown_account",
               f"No account '{args.account}'. Known: {', '.join(a['name'] for a in accounts)}")
    account = matches[0]

    conn = md.connect(account)
    try:
        # readonly=True: drafting a reply must not change an unread count.
        typ, _ = conn.select(account.get("mailbox", "INBOX"), readonly=True)
        if typ != "OK":
            md.die("select_failed", account.get("mailbox", "INBOX"))
        original = fetch_original(conn, args.uid)
        if original is None:
            md.die("uid_not_found", f"UID {args.uid} not in {account['name']}.")

        reply = build_reply(original, account, body)
        drafts = account.get("drafts_mailbox") or "Drafts"

        print(f"--- draft for {account['name']} (UID {args.uid}) ---")
        print(f"From:    {reply['From']}")
        print(f"To:      {reply['To']}")
        print(f"Subject: {reply['Subject']}")
        print(f"Thread:  In-Reply-To {reply.get('In-Reply-To') or '(none — will not thread)'}")
        print(f"Drafts:  {drafts}")
        print("---")
        print(reply.get_content())

        if not args.append:
            print("--- dry run. Nothing written. Re-run with --append to save the draft. ---")
            return 0

        typ, _ = conn.append(drafts, "\\Draft", imaplib.Time2Internaldate(time.time()),
                             reply.as_bytes())
        if typ != "OK":
            md.die("append_failed", f"Could not write to '{drafts}'.")
        print(f"--- saved to {drafts}. Open Mail, review it, and press Send. ---")
    finally:
        md.close_quietly(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
