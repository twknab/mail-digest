#!/usr/bin/env python3
"""Execute approved unsubscribes. Never runs from the schedule.

Takes a plan -- a small JSON file naming exactly which senders to act on and
how -- and carries it out. The plan is a separate, readable artefact on purpose:
you can look at precisely what is about to happen before anything fires.

    # 1. build a plan from a junk report, for senders you picked
    junk_actions.py --from-report report.json --address a@x.com --address b@y.com > plan.json

    # 2. read plan.json yourself, then
    junk_actions.py --plan plan.json --execute

Without --execute this is a dry run and touches nothing.

Two safety rules are enforced in code, not left to judgement:

  * One-click POSTs (RFC 8058) go only to https, and only to senders whose mail
    actually carried List-Unsubscribe-Post. These are real companies with real
    compliance obligations.
  * Anything else is never auto-fired. For a sender with no unsubscribe -- the
    profile of actual spam -- engaging confirms your address is live, so the
    recommendation is a filter and this tool refuses to "unsubscribe" at all.
"""

from __future__ import annotations

import argparse
import json
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import mail_digest as md

TIMEOUT = 30
USER_AGENT = "mail-digest/1.0 (unsubscribe)"
AUTO_FIREABLE = {"one_click", "mailto"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_plan(report: dict, addresses: list[str]) -> dict:
    wanted = {a.strip().lower() for a in addresses}
    by_addr = {s["address"]: s for s in report.get("senders", [])}

    actions, skipped = [], []
    for addr in sorted(wanted):
        sender = by_addr.get(addr)
        if sender is None:
            skipped.append({"address": addr, "reason": "not in report"})
            continue
        rec = sender.get("recommendation")
        if rec not in AUTO_FIREABLE:
            skipped.append({
                "address": addr,
                "reason": f"recommendation is '{rec}' -- {sender.get('why', '')}",
            })
            continue
        actions.append({
            "address": addr,
            "display": sender.get("display", addr),
            "action": rec,
            "url": sender["unsubscribe"].get("http"),
            "mailto": sender["unsubscribe"].get("mailto"),
            "account": (sender.get("accounts") or [None])[0],
            "count": sender.get("count"),
        })
    return {"created_at": now_iso(), "actions": actions, "skipped": skipped}


def do_one_click(action: dict) -> dict:
    url = action.get("url") or ""
    if not url.lower().startswith("https://"):
        return {"ok": False, "detail": f"refusing non-https unsubscribe URL: {url!r}"}

    data = urllib.parse.urlencode({"List-Unsubscribe": "One-Click"}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT,
                                    context=ssl.create_default_context()) as resp:
            return {"ok": 200 <= resp.status < 400, "detail": f"HTTP {resp.status}"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "detail": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def do_mailto(action: dict, accounts: dict) -> dict:
    target = action.get("mailto") or ""
    if not target.lower().startswith("mailto:"):
        return {"ok": False, "detail": f"not a mailto URI: {target!r}"}

    parsed = urllib.parse.urlparse(target)
    to_addr = parsed.path
    params = urllib.parse.parse_qs(parsed.query)
    subject = (params.get("subject") or ["unsubscribe"])[0]
    body = (params.get("body") or ["Please unsubscribe this address."])[0]

    account = accounts.get(action.get("account"))
    if account is None:
        return {"ok": False, "detail": f"unknown account {action.get('account')!r}"}
    host = account.get("smtp_host")
    if not host:
        return {"ok": False, "detail": f"account '{account['name']}' has no smtp_host"}

    msg = EmailMessage()
    msg["From"] = account["user"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, int(account.get("smtp_port", 587)), timeout=TIMEOUT) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(account["user"], md.password_for(account))
            smtp.send_message(msg)
        return {"ok": True, "detail": f"unsubscribe mail sent to {to_addr}"}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def record(ledger: dict, action: dict, result: dict) -> None:
    """Log every attempt. The next junk report reads this to spot senders who
    ignored an unsubscribe, which is the part that actually shrinks an inbox."""
    ledger[action["address"]] = {
        "action": action["action"],
        "date": now_iso(),
        "account": action.get("account"),
        "ok": result["ok"],
        "detail": result["detail"],
    }


def save_ledger(ledger: dict) -> None:
    md.HOME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = md.LEDGER_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, indent=2))
    tmp.replace(md.LEDGER_FILE)


def main() -> int:
    default_config = Path(__file__).resolve().parent / "accounts.json"
    p = argparse.ArgumentParser(description="Execute approved unsubscribes.")
    p.add_argument("--config", type=Path, default=default_config)
    p.add_argument("--from-report", type=Path, help="Junk report JSON to build a plan from.")
    p.add_argument("--address", action="append", default=[],
                   help="Sender to act on; repeatable. Used with --from-report.")
    p.add_argument("--plan", type=Path, help="Plan JSON to execute.")
    p.add_argument("--execute", action="store_true",
                   help="Actually do it. Without this, nothing is sent or POSTed.")
    args = p.parse_args()

    if args.from_report and not args.plan:
        report = json.loads(args.from_report.read_text())
        plan = build_plan(report, args.address)
        if not args.execute:
            print(json.dumps(plan, indent=2))
            return 0
    elif args.plan:
        plan = json.loads(args.plan.read_text())
    else:
        p.error("give --plan, or --from-report with one or more --address")

    accounts = {a["name"]: a for a in md.load_accounts(args.config)}
    ledger = md.load_ledger()
    results = []

    for action in plan.get("actions", []):
        kind = action.get("action")
        if kind not in AUTO_FIREABLE:
            results.append({**action, "ok": False, "detail": f"refusing action '{kind}'"})
            continue
        if not args.execute:
            results.append({**action, "ok": None,
                            "detail": f"dry run -- would {kind} {action['address']}"})
            continue
        result = do_one_click(action) if kind == "one_click" else do_mailto(action, accounts)
        record(ledger, action, result)
        results.append({**action, **result})

    if args.execute:
        save_ledger(ledger)

    ok = sum(1 for r in results if r.get("ok") is True)
    failed = sum(1 for r in results if r.get("ok") is False)
    print(json.dumps({
        "executed": args.execute,
        "attempted": len(results),
        "succeeded": ok,
        "failed": failed,
        "skipped": plan.get("skipped", []),
        "results": results,
    }, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
