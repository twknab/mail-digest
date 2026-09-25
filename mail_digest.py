#!/usr/bin/env python3
"""Read new mail from every configured IMAP account and emit it as JSON.

This does the mechanical half of the job only: connect, fetch what is genuinely
new, strip obvious bulk, and hand the rest over as structured JSON. It makes no
judgement about what is "important" -- that is the model's job, downstream.

Three properties are load-bearing and must survive any future edit:

  * It never marks anything as read. Mailboxes are opened read-only and bodies
    are fetched with BODY.PEEK, so running this leaves your unread count alone.
  * It never sends, deletes, moves, or flags anything. Strictly a reader.
  * State is per account+mailbox, so a failure on one account cannot lose the
    other's position in its inbox.

Two modes:

    mail_digest.py                     new mail since last run, ready to triage
    mail_digest.py --junk-report       who is flooding you, and how to stop them

Passwords come from the macOS Keychain (see accounts.json -> keychain_service),
or from MAIL_DIGEST_PW_<ACCOUNT> in the environment for testing.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import imaplib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr
from pathlib import Path

HOME_DIR = Path.home() / ".mail-digest"
STATE_FILE = HOME_DIR / "state.json"
CONTACTS_FILE = HOME_DIR / "contacts.txt"
LEDGER_FILE = HOME_DIR / "junk-ledger.json"

SNIPPET_CHARS = 700
SENT_LOOKBACK_DAYS = 365
SENT_SCAN_CAP = 2000

# Any one of these means the message was sent to a list rather than to you --
# they are set by the sender's mailing infrastructure, not by a human.
BULK_HEADERS = ("list-unsubscribe", "list-id", "list-post", "auto-submitted")
BULK_PRECEDENCE = {"bulk", "list", "junk", "auto_reply"}

# Gmail's category tabs, exposed over IMAP as labels. A far stronger junk
# signal than header sniffing, and free once X-GM-EXT-1 is advertised.
GMAIL_BULK_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"}

ACTION_WORDS = (
    "urgent", "asap", "review", "approve", "approval", "decision", "decide",
    "sign", "signature", "deadline", "due", "confirm", "respond", "reply",
    "action required", "needs your", "please advise", "waiting on you",
)

# How long an unsubscribe gets to take effect before we call it ignored.
UNSUB_GRACE_DAYS = 14


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def decode(raw: str | None) -> str:
    """Decode RFC 2047 header encoding into plain text, tolerating junk."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:
        return str(raw).strip()


def addr_of(raw: str) -> str:
    """Bare lowercase address out of a From/To header value.

    parseaddr() happily returns the first bare token for malformed input
    ("not an address" -> "not"), which would key the junk report on a sender
    that does not exist, so require something that actually looks like an
    address before believing it.
    """
    _, addr = parseaddr(raw or "")
    addr = addr.strip().lower()
    return addr if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", addr) else ""


def domain_of(addr: str) -> str:
    return addr.split("@")[-1] if "@" in addr else ""


def body_snippet(msg: email.message.Message) -> str:
    """First chunk of readable text, HTML stripped, whitespace collapsed."""
    part = None
    try:
        part = msg.get_body(preferencelist=("plain",)) or msg.get_body(preferencelist=("html",))
    except Exception:
        pass
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:
        return ""
    if not text:
        return ""
    if part.get_content_type() == "text/html":
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > SNIPPET_CHARS:
        text = text[:SNIPPET_CHARS].rstrip() + "\u2026"
    return text


def unsubscribe_info(msg: email.message.Message) -> dict:
    """Split List-Unsubscribe into its http and mailto forms.

    one_click is RFC 8058: the sender promises a bare POST will unsubscribe
    you with no confirmation page and no browser. It is the only unsubscribe
    we are willing to fire automatically.
    """
    raw = msg.get("list-unsubscribe") or ""
    http_url = mailto = None
    for target in re.findall(r"<([^>]+)>", raw):
        target = target.strip()
        low = target.lower()
        if low.startswith("http") and http_url is None:
            http_url = target
        elif low.startswith("mailto:") and mailto is None:
            mailto = target
    post = (msg.get("list-unsubscribe-post") or "").lower()
    return {
        "http": http_url,
        "mailto": mailto,
        "one_click": "one-click" in post and http_url is not None,
    }


def is_bulk(msg: email.message.Message, labels: list[str]) -> bool:
    if any(msg.get(h) for h in BULK_HEADERS):
        return True
    if (msg.get("precedence") or "").strip().lower() in BULK_PRECEDENCE:
        return True
    return any(lbl in GMAIL_BULK_LABELS for lbl in labels)


# --------------------------------------------------------------------------
# config, state, credentials
# --------------------------------------------------------------------------

def load_accounts(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        die("missing_config", f"No accounts file at {path}. Copy accounts.example.json.")
    except json.JSONDecodeError as exc:
        die("bad_config", f"{path} is not valid JSON: {exc}")
    accounts = data.get("accounts") or []
    if not accounts:
        die("bad_config", f"{path} has no accounts.")
    return accounts


def password_for(account: dict) -> str:
    """Keychain first; env override exists so tests never touch the Keychain."""
    env_key = f"MAIL_DIGEST_PW_{account['name'].upper()}"
    if os.environ.get(env_key):
        return os.environ[env_key]

    service = account.get("keychain_service")
    if not service:
        die("missing_credentials", f"Account '{account['name']}' has no keychain_service.")
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account["user"], "-w"],
            capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        die("no_keychain", f"`security` not found. Set {env_key} instead.")
    except subprocess.TimeoutExpired:
        die("keychain_timeout", "Keychain did not respond; is it unlocked?")
    if out.returncode != 0:
        die("missing_credentials",
            f"No Keychain item '{service}' for {account['user']}. Add it with:\n"
            f"  security add-generic-password -s {service} -a {account['user']} -w")
    return out.stdout.strip()


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    HOME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def load_contacts() -> set[str]:
    """Optional allowlist: one address or domain per line, # for comments."""
    try:
        lines = CONTACTS_FILE.read_text().splitlines()
    except Exception:
        return set()
    return {ln.strip().lower() for ln in lines if ln.strip() and not ln.strip().startswith("#")}


def load_ledger() -> dict:
    try:
        return json.loads(LEDGER_FILE.read_text())
    except Exception:
        return {}


def known_contact(sender_addr: str, contacts: set[str]) -> bool:
    if not sender_addr:
        return False
    return sender_addr in contacts or domain_of(sender_addr) in contacts


def die(code: str, detail: str) -> None:
    print(json.dumps({"error": code, "detail": detail}, indent=2), file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------
# IMAP
# --------------------------------------------------------------------------

def connect(account: dict) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(account.get("host"), int(account.get("port", 993)))
    conn.login(account["user"], password_for(account))
    return conn


def supports_gmail_ext(conn: imaplib.IMAP4_SSL) -> bool:
    try:
        return "X-GM-EXT-1" in str(conn.capabilities).upper()
    except Exception:
        return False


def parse_meta(chunks) -> tuple[list[str], list[str]]:
    """Pull FLAGS and X-GM-LABELS out of an untagged FETCH response."""
    blob = ""
    for chunk in chunks:
        if isinstance(chunk, tuple):
            blob += chunk[0].decode(errors="replace")
        elif isinstance(chunk, bytes):
            blob += chunk.decode(errors="replace")
    flags = re.findall(r"\\(\w+)", blob.split("X-GM-LABELS")[0])
    labels: list[str] = []
    m = re.search(r"X-GM-LABELS \(([^)]*)\)", blob)
    if m:
        labels = [x.strip().strip('"').lstrip("\\") for x in m.group(1).split() if x.strip()]
    return flags, labels


def search_uids(conn, last_uid: int | None, since_hours: int) -> list[int]:
    if last_uid:
        criteria = ["UID", f"{last_uid + 1}:*"]
    else:
        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).strftime("%d-%b-%Y")
        criteria = ["SINCE", since]
    typ, data = conn.uid("SEARCH", None, *criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    uids = [int(x) for x in data[0].split()]
    # "UID n:*" always returns at least the highest UID even when nothing is
    # newer than n, so drop anything already accounted for.
    return [u for u in uids if not last_uid or u > last_uid]


def fetch_full(conn, uid: int, gmail: bool) -> dict | None:
    spec = "(FLAGS X-GM-LABELS BODY.PEEK[])" if gmail else "(FLAGS BODY.PEEK[])"
    typ, data = conn.uid("FETCH", str(uid), spec)
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        return None
    flags, labels = parse_meta(data)
    msg = email.message_from_bytes(data[0][1], policy=email.policy.default)
    return build_record(uid, msg, flags, labels, snippet=True)


def fetch_headers(conn, uid: int, gmail: bool) -> dict | None:
    """Junk reporting never needs bodies -- headers are far cheaper."""
    fields = "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE TO CC DELIVERED-TO " \
             "X-ORIGINAL-TO LIST-UNSUBSCRIBE LIST-UNSUBSCRIBE-POST LIST-ID " \
             "LIST-POST PRECEDENCE AUTO-SUBMITTED)]"
    spec = f"(FLAGS X-GM-LABELS {fields})" if gmail else f"(FLAGS {fields})"
    typ, data = conn.uid("FETCH", str(uid), spec)
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        return None
    flags, labels = parse_meta(data)
    msg = email.message_from_bytes(data[0][1], policy=email.policy.default)
    return build_record(uid, msg, flags, labels, snippet=False)


def delivered_addrs(msg) -> list[str]:
    """Every address this landed on, most authoritative first.

    Delivered-To and X-Original-To survive BCC and forwarding, where To does
    not -- mail sent to an alias you were BCC'd on has someone else in To.
    """
    out: list[str] = []
    for header in ("delivered-to", "x-original-to", "to", "cc"):
        for _, addr in getaddresses(msg.get_all(header, [])):
            addr = (addr or "").strip().lower()
            if addr and addr not in out:
                out.append(addr)
    return out


def account_addresses(account: dict) -> list[str]:
    """Every address that legitimately belongs to this login."""
    out = [(account.get("user") or "").strip().lower()]
    for alias in (account.get("alias_roles") or {}):
        alias = alias.strip().lower()
        if alias and alias not in out:
            out.append(alias)
    return [a for a in out if a]


def identity_for(record: dict, account: dict) -> str:
    """Which of my addresses this message actually landed on.

    Aliases share one INBOX, so the account's primary address is a poor label:
    grouping by it would pile work, personal and shopping mail together. This
    is also what a reply must be sent from, so the two must never disagree --
    mail_reply delegates here rather than keeping its own copy.
    """
    mine = account_addresses(account)
    for addr in record.get("delivered_to") or []:
        if addr in mine:
            return addr
    return (account.get("user") or "").strip().lower()


def role_for(record: dict, account: dict) -> str:
    """Which bundle this message belongs to.

    Gmail splits by login, so the account's own role is the answer. iCloud
    aliases all deliver into one INBOX, so the only thing distinguishing
    business from shopping mail is which alias it was addressed to.
    """
    alias_roles = {k.lower(): v for k, v in (account.get("alias_roles") or {}).items()}
    if alias_roles:
        for addr in record.get("delivered_to") or []:
            if addr in alias_roles:
                return alias_roles[addr]
    return account.get("role") or "personal"


def build_record(uid: int, msg, flags: list[str], labels: list[str], snippet: bool) -> dict:
    sender = decode(msg.get("from"))
    subject = decode(msg.get("subject"))
    text = body_snippet(msg) if snippet else ""
    haystack = f"{subject} {text}".lower()
    return {
        "uid": uid,
        "from": sender,
        "from_addr": addr_of(msg.get("from") or ""),
        "subject": subject,
        "date": decode(msg.get("date")),
        "flagged": "Flagged" in flags,
        "unread": "Seen" not in flags,
        "labels": labels,
        "bulk": is_bulk(msg, labels),
        "unsubscribe": unsubscribe_info(msg),
        "action_words": sorted({w for w in ACTION_WORDS if w in haystack}),
        "snippet": text,
        "delivered_to": delivered_addrs(msg),
    }


def sent_correspondents(conn, account: dict) -> set[str]:
    """Everyone you have written to -- they are protected from the kill list."""
    mailbox = account.get("sent_mailbox")
    if not mailbox:
        return set()
    try:
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            return set()
        since = (datetime.now(timezone.utc) - timedelta(days=SENT_LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        typ, data = conn.uid("SEARCH", None, "SINCE", since)
        if typ != "OK" or not data or not data[0]:
            return set()
        uids = [int(x) for x in data[0].split()][-SENT_SCAN_CAP:]
    except Exception:
        return set()

    found: set[str] = set()
    for uid in uids:
        try:
            typ, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[HEADER.FIELDS (TO CC)])")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            msg = email.message_from_bytes(data[0][1], policy=email.policy.default)
            values = [v for v in (msg.get_all("to", []) + msg.get_all("cc", []))]
            for _, addr in getaddresses(values):
                if addr:
                    found.add(addr.strip().lower())
        except Exception:
            continue
    return found


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def run_digest(accounts: list[dict], args, contacts: set[str]) -> dict:
    state = {} if args.reset else load_state()
    summaries, messages = [], []

    for account in accounts:
        name = account["name"]
        mailbox = account.get("mailbox", "INBOX")
        key = f"{name}:{mailbox}"
        last_uid = state.get(key, {}).get("last_uid")
        summary = {"name": name, "user": account.get("user"), "first_run": last_uid is None}

        try:
            conn = connect(account)
        except imaplib.IMAP4.error as exc:
            summaries.append({**summary, "error": "login_failed", "detail": str(exc)})
            continue
        except OSError as exc:
            summaries.append({**summary, "error": "network_failed", "detail": str(exc)})
            continue

        try:
            gmail = supports_gmail_ext(conn)
            typ, _ = conn.select(mailbox, readonly=True)
            if typ != "OK":
                summaries.append({**summary, "error": "select_failed", "detail": mailbox})
                continue

            uids = search_uids(conn, last_uid, args.since_hours)
            truncated = len(uids) > args.max
            if truncated:
                uids = uids[-args.max:]

            dropped = 0
            for uid in uids:
                try:
                    item = fetch_full(conn, uid, gmail)
                except Exception:
                    continue
                if item is None:
                    continue
                item["account"] = name
                item["known_contact"] = known_contact(item["from_addr"], contacts)
                item["role"] = role_for(item, account)
                item["identity"] = identity_for(item, account)
                # Bulk survives only if you flagged it or know the sender -- a
                # newsletter you starred is still something you wanted.
                if item["bulk"] and not args.include_bulk and not (
                    item["flagged"] or item["known_contact"]
                ):
                    dropped += 1
                    continue
                messages.append(item)

            highest = max(uids) if uids else last_uid
            if not args.no_save and highest:
                state.setdefault(key, {})
                state[key]["last_uid"] = highest
                state[key]["last_run"] = datetime.now(timezone.utc).isoformat()

            summaries.append({**summary, "new_count": len(uids),
                              "bulk_dropped": dropped, "truncated": truncated})
        finally:
            close_quietly(conn)

    if not args.no_save:
        save_state(state)

    return {
        "mode": "digest",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "contacts_loaded": len(contacts),
        "accounts": summaries,
        "messages": messages,
    }


def classify_sender(entry: dict, ledger: dict, now: datetime, contacts: set[str]) -> dict:
    """Turn a bulk-sender tally into a recommendation.

    Pure and side-effect free on purpose: this is the judgement that decides
    whether we unsubscribe, filter, or leave a sender alone, so it is the part
    that most needs to be unit tested without a mailbox.
    """
    if isinstance(entry.get("categories"), set):
        entry["categories"] = sorted(entry["categories"])
    entry.setdefault("ever_replied", False)

    # Protection wins over volume. Someone you have written to, flagged, or
    # listed as a contact is never a candidate for removal, however loud.
    entry["protected"] = (
        entry["ever_replied"]
        or known_contact(entry["address"], contacts)
        or entry.get("flagged_count", 0) > 0
    )

    record = ledger.get(entry["address"])
    entry["previously_actioned"] = bool(record)
    entry["unsubscribe_ignored"] = False
    if record and record.get("action") in ("one_click", "mailto"):
        try:
            when = datetime.fromisoformat(record["date"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            # Still arriving well after we asked them to stop.
            if (now - when).days >= UNSUB_GRACE_DAYS and entry["count"] > 0:
                entry["unsubscribe_ignored"] = True
        except Exception:
            pass

    u = entry["unsubscribe"]
    if entry["unsubscribe_ignored"]:
        entry["recommendation"] = "hard_filter"
        entry["why"] = "Unsubscribed, still arriving. Block it server-side."
    elif entry["protected"]:
        entry["recommendation"] = "keep"
        entry["why"] = "You have replied to, flagged, or listed this sender."
    elif u["one_click"]:
        entry["recommendation"] = "one_click"
        entry["why"] = "Supports RFC 8058 one-click unsubscribe. Safe to fire."
    elif u["mailto"]:
        entry["recommendation"] = "mailto"
        entry["why"] = "Unsubscribe by email."
    elif u["http"]:
        entry["recommendation"] = "manual_link"
        entry["why"] = "Unsubscribe page only -- needs a human to open it."
    else:
        entry["recommendation"] = "hard_filter"
        entry["why"] = "No unsubscribe offered. Filter rather than engage."
    return entry


def run_junk_report(accounts: list[dict], args, contacts: set[str]) -> dict:
    ledger = load_ledger()
    senders: dict[str, dict] = {}
    summaries = []

    for account in accounts:
        name = account["name"]
        mailbox = account.get("mailbox", "INBOX")
        try:
            conn = connect(account)
        except (imaplib.IMAP4.error, OSError) as exc:
            summaries.append({"name": name, "error": "connect_failed", "detail": str(exc)})
            continue

        try:
            gmail = supports_gmail_ext(conn)
            replied = sent_correspondents(conn, account)

            typ, _ = conn.select(mailbox, readonly=True)
            if typ != "OK":
                summaries.append({"name": name, "error": "select_failed", "detail": mailbox})
                continue

            since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%d-%b-%Y")
            typ, data = conn.uid("SEARCH", None, "SINCE", since)
            uids = [int(x) for x in data[0].split()] if (typ == "OK" and data and data[0]) else []

            scanned = 0
            for uid in uids:
                try:
                    item = fetch_headers(conn, uid, gmail)
                except Exception:
                    continue
                if item is None or not item["bulk"]:
                    continue
                scanned += 1
                addr = item["from_addr"] or "(unknown)"
                entry = senders.setdefault(addr, {
                    "address": addr,
                    "display": item["from"],
                    "domain": domain_of(addr),
                    "accounts": [],
                    "count": 0,
                    "flagged_count": 0,
                    "categories": set(),
                    "unsubscribe": {"http": None, "mailto": None, "one_click": False},
                })
                entry["count"] += 1
                entry["flagged_count"] += 1 if item["flagged"] else 0
                if name not in entry["accounts"]:
                    entry["accounts"].append(name)
                entry["categories"].update(l for l in item["labels"] if l in GMAIL_BULK_LABELS)
                for field in ("http", "mailto"):
                    if not entry["unsubscribe"][field] and item["unsubscribe"][field]:
                        entry["unsubscribe"][field] = item["unsubscribe"][field]
                entry["unsubscribe"]["one_click"] |= item["unsubscribe"]["one_click"]

            for addr, entry in senders.items():
                if addr in replied:
                    entry["ever_replied"] = True

            summaries.append({"name": name, "scanned_bulk": scanned, "window_days": args.days})
        finally:
            close_quietly(conn)

    now = datetime.now(timezone.utc)
    ranked = [classify_sender(e, ledger, now, contacts) for e in senders.values()]

    ranked.sort(key=lambda e: (not e["unsubscribe_ignored"], -e["count"]))
    return {
        "mode": "junk_report",
        "checked_at": now.isoformat(),
        "window_days": args.days,
        "accounts": summaries,
        "total_bulk_senders": len(ranked),
        "senders": ranked[:args.top],
    }


def close_quietly(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass
    try:
        conn.logout()
    except Exception:
        pass


def main() -> int:
    default_config = Path(__file__).resolve().parent / "accounts.json"
    p = argparse.ArgumentParser(description="Read new mail from all configured IMAP accounts.")
    p.add_argument("--config", type=Path, default=default_config)
    p.add_argument("--account", action="append",
                   help="Limit to this account name; repeatable. Default: all.")
    p.add_argument("--since-hours", type=int, default=24,
                   help="How far back to look on the very first run (default: 24).")
    p.add_argument("--max", type=int, default=60, help="Cap on messages per account per run.")
    p.add_argument("--include-bulk", action="store_true", help="Keep newsletters and list mail.")
    p.add_argument("--reset", action="store_true", help="Forget saved position.")
    p.add_argument("--no-save", action="store_true", help="Do not advance saved position.")
    p.add_argument("--junk-report", action="store_true", help="Who is flooding you, and how to stop it.")
    p.add_argument("--days", type=int, default=30, help="Junk report lookback (default: 30).")
    p.add_argument("--top", type=int, default=40, help="Junk report: how many senders to list.")
    args = p.parse_args()

    accounts = load_accounts(args.config)
    if args.account:
        wanted = {a.lower() for a in args.account}
        accounts = [a for a in accounts if a["name"].lower() in wanted]
        if not accounts:
            die("unknown_account", f"No account matching {sorted(wanted)} in {args.config}.")

    contacts = load_contacts()
    result = run_junk_report(accounts, args, contacts) if args.junk_report \
        else run_digest(accounts, args, contacts)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
