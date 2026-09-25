#!/usr/bin/env python3
"""Tests for plan building and the safety refusals. No network, no mailbox."""

import junk_actions as ja

PASSED = FAILED = 0


def check(label, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL {label}\n       got:  {got!r}\n       want: {want!r}")


REPORT = {"senders": [
    {"address": "news@shop.example", "display": "Shop", "accounts": ["gmail"], "count": 40,
     "recommendation": "one_click", "why": "",
     "unsubscribe": {"http": "https://shop.example/u/1", "mailto": None, "one_click": True}},
    {"address": "list@club.example", "display": "Club", "accounts": ["icloud"], "count": 12,
     "recommendation": "mailto", "why": "",
     "unsubscribe": {"http": None, "mailto": "mailto:off@club.example?subject=stop", "one_click": False}},
    {"address": "spam@bad.example", "display": "Bad", "accounts": ["gmail"], "count": 90,
     "recommendation": "hard_filter", "why": "No unsubscribe offered.",
     "unsubscribe": {"http": None, "mailto": None, "one_click": False}},
    {"address": "boss@work.example", "display": "Boss", "accounts": ["gmail"], "count": 5,
     "recommendation": "keep", "why": "You have replied to this sender.",
     "unsubscribe": {"http": "https://work.example/u", "mailto": None, "one_click": True}},
]}

print("build_plan")
plan = ja.build_plan(REPORT, ["news@shop.example", "list@club.example"])
check("two actions planned", len(plan["actions"]), 2)
check("one-click carried", plan["actions"][1]["url"], "https://shop.example/u/1")
check("account carried", plan["actions"][0]["account"], "icloud")

# The two refusals that matter: never "unsubscribe" from spam, never from a
# sender we decided to protect.
plan = ja.build_plan(REPORT, ["spam@bad.example"])
check("spam not planned", plan["actions"], [])
check("spam skipped with reason", "hard_filter" in plan["skipped"][0]["reason"], True)

plan = ja.build_plan(REPORT, ["boss@work.example"])
check("protected sender not planned", plan["actions"], [])
check("protected skipped", "keep" in plan["skipped"][0]["reason"], True)

plan = ja.build_plan(REPORT, ["ghost@nowhere.example"])
check("unknown address skipped", plan["skipped"][0]["reason"], "not in report")

# Case and whitespace should not let a sender through unmatched.
plan = ja.build_plan(REPORT, ["  News@Shop.Example  "])
check("address normalised", len(plan["actions"]), 1)

print("do_one_click refusals")
check("plain http refused",
      ja.do_one_click({"url": "http://shop.example/u"})["ok"], False)
check("http refusal explains",
      "non-https" in ja.do_one_click({"url": "http://shop.example/u"})["detail"], True)
check("empty url refused", ja.do_one_click({"url": ""})["ok"], False)
check("javascript url refused", ja.do_one_click({"url": "javascript:alert(1)"})["ok"], False)
check("file url refused", ja.do_one_click({"url": "file:///etc/passwd"})["ok"], False)

print("do_mailto refusals")
check("non-mailto refused", ja.do_mailto({"mailto": "https://x"}, {})["ok"], False)
check("unknown account refused",
      ja.do_mailto({"mailto": "mailto:a@b.example", "account": "nope"}, {})["ok"], False)
check("account without smtp refused",
      ja.do_mailto({"mailto": "mailto:a@b.example", "account": "x"},
                   {"x": {"name": "x", "user": "u@x", "smtp_host": ""}})["ok"], False)

print()
print(f"{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
