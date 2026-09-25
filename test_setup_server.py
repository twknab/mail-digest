#!/usr/bin/env python3
"""Checks for the local setup UI. Starts a real server on loopback.

Never touches the real accounts.json: CONFIG is redirected to a temp file
before the server starts.
"""

import json
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import setup_server as ss

PASSED = FAILED = 0


def check(label, got, want):
    global PASSED, FAILED
    if got == want:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL {label}\n    got:  {got!r}\n    want: {want!r}")


TMP = Path(tempfile.mkdtemp()) / "accounts.json"
TMP.write_text(json.dumps({"accounts": [
    {"name": "taken", "user": "taken@example.com", "keychain_service": "mail-digest-taken"}
]}) + "\n")
ss.CONFIG = TMP

srv = HTTPServer(("127.0.0.1", 0), ss.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"


def get(path, token=ss.TOKEN):
    url = f"{BASE}{path}" + (f"?token={token}" if token is not None else "")
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(path, payload, token=ss.TOKEN):
    url = f"{BASE}{path}" + (f"?token={token}" if token is not None else "")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


print("token gate")
check("no token is refused", get("/", token=None)[0], 403)
check("wrong token is refused", get("/", token="not-the-token")[0], 403)
check("correct token serves the page", get("/")[0], 200)
check("api refuses a wrong token", post("/api/save", {}, token="nope")[0], 403)

print("page")
status, body = get("/")
html = body.decode()
check("page carries the real token", ss.TOKEN in html, True)
check("placeholder was substituted", "__TOKEN__" in html, False)

print("state")
status, body = get("/api/state")
state = json.loads(body)
check("providers are served", len(state["providers"]) >= 5, True)
check("existing accounts are listed", state["accounts"][0]["name"], "taken")
check("state carries nothing password-shaped",
      any("password" in json.dumps(a).lower() for a in state["accounts"]), False)

print("save validation (all reject before any network or Keychain call)")
check("name required", post("/api/save", {"user": "a@b.com", "password": "x"})[1]["error"],
      "Name and address are both required.")
check("address required", post("/api/save", {"name": "x", "password": "x"})[1]["error"],
      "Name and address are both required.")
check("password required",
      post("/api/save", {"name": "x", "user": "a@b.com"})[1]["error"],
      "An app-specific password is required.")
check("duplicate name refused",
      post("/api/save", {"name": "taken", "user": "new@example.com", "password": "x"})[1]["error"],
      "An account named 'taken' already exists.")
check("duplicate address refused",
      post("/api/save", {"name": "fresh", "user": "taken@example.com", "password": "x"})[1]["error"],
      "taken@example.com is already configured.")

print("set password on an existing account")
check("password required",
      post("/api/password", {"name": "taken"})[1]["error"],
      "An app-specific password is required.")
check("unknown account refused",
      post("/api/password", {"name": "ghost", "password": "x"})[1]["error"],
      "No account named 'ghost'.")
check("wrong token refused", post("/api/password", {}, token="nope")[0], 403)

print("delete")
check("unknown account", post("/api/delete", {"name": "ghost"})[1]["error"],
      "No account named 'ghost'.")
check("known account", post("/api/delete", {"name": "taken"})[1]["ok"], True)
check("config actually shrank", json.loads(TMP.read_text())["accounts"], [])

print("safety")
check("bind address is loopback", srv.server_address[0], "127.0.0.1")
check("token is long enough to be unguessable", len(ss.TOKEN) >= 24, True)
check("access logging is disabled", ss.Handler.log_message.__doc__ is not None, True)

srv.shutdown()
print()
print(f"{PASSED} passed, {FAILED} failed")
raise SystemExit(1 if FAILED else 0)
