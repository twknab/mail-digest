#!/usr/bin/env python3
"""Local setup UI. Configure accounts in a browser instead of editing JSON.

    python3 setup_server.py

Opens http://127.0.0.1:<port>/?token=<random> and prints the URL.

Why a browser form is safe enough here, given an app password is involved:

  * The socket binds to 127.0.0.1 only, so nothing off this machine can reach
    it -- not the LAN, not a container, not a colleague on the same wifi.
  * Every request must carry a random token minted at startup. A stray page in
    another tab guessing the port still cannot talk to it.
  * The password is never written to disk by this tool and never appears in a
    response body. It goes form -> process memory -> `security` over stdin, so
    it stays out of argv and out of `ps`.
  * The server is short-lived: it serves setup and you stop it.

Plain HTTP is deliberate. TLS on loopback would mean shipping a certificate or
minting one, and the traffic never leaves the machine.
"""

from __future__ import annotations

import json
import secrets
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import imaplib

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "accounts.json"
PROVIDERS = HERE / "providers.json"
TOKEN = secrets.token_urlsafe(24)


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------

def load_providers() -> list[dict]:
    return json.loads(PROVIDERS.read_text()).get("providers", [])


def load_config() -> dict:
    if CONFIG.exists():
        return json.loads(CONFIG.read_text())
    return {"accounts": []}


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")


def keychain_store(service: str, user: str, password: str) -> tuple[bool, str]:
    """Write to the login Keychain without the password touching argv.

    `security -w` prompts twice, so the value goes down stdin twice. -U updates
    in place; -T /usr/bin/security is what stops macOS raising an auth dialog
    at 08:07 when nobody is there to dismiss it.
    """
    try:
        proc = subprocess.run(
            ["security", "add-generic-password", "-s", service, "-a", user,
             "-T", "/usr/bin/security", "-U", "-w"],
            input=f"{password}\n{password}\n", capture_output=True, text=True, timeout=20,
        )
    except FileNotFoundError:
        return False, "`security` not found -- is this macOS?"
    except subprocess.TimeoutExpired:
        return False, "Keychain did not respond."
    if proc.returncode != 0:
        return False, (proc.stderr or "Keychain refused the item.").strip()
    return True, ""


def imap_check(host: str, port: int, user: str, password: str) -> tuple[bool, str]:
    """Prove the credentials work before we store anything.

    Logs in and immediately logs out. Nothing is selected, so nothing can be
    marked read by a connection test.
    """
    try:
        conn = imaplib.IMAP4_SSL(host, int(port), timeout=20)
    except Exception as exc:
        return False, f"Could not reach {host}:{port} -- {exc}"
    try:
        conn.login(user, password)
    except imaplib.IMAP4.error as exc:
        detail = str(exc)
        hint = ""
        if "AUTHENTICATIONFAILED" in detail.upper() or "Invalid" in detail:
            hint = " (app-specific password required; your normal password will not work)"
        return False, f"Login refused{hint}: {detail}"
    except Exception as exc:
        return False, f"Login failed: {exc}"
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return True, ""


# --------------------------------------------------------------------------
# request handling
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "mail-digest-setup"

    def log_message(self, *args):  # noqa: D102
        """Silence the access log: request lines can carry query parameters."""

    # -- helpers ----------------------------------------------------------

    def _authorised(self, parsed) -> bool:
        supplied = parse_qs(parsed.query).get("token", [""])[0]
        header = self.headers.get("X-Setup-Token", "")
        return secrets.compare_digest(supplied, TOKEN) or secrets.compare_digest(header, TOKEN)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    # -- routes -----------------------------------------------------------

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if not self._authorised(parsed):
            self._send(403, b"Missing or bad setup token.", "text/plain")
            return
        if parsed.path == "/":
            self._send(200, PAGE.replace("__TOKEN__", TOKEN).encode(), "text/html; charset=utf-8")
        elif parsed.path == "/api/state":
            cfg = load_config()
            # Never return anything credential-shaped, even by accident.
            self._json(200, {"providers": load_providers(), "accounts": cfg.get("accounts", [])})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if not self._authorised(parsed):
            self._json(403, {"ok": False, "error": "Missing or bad setup token."})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "Malformed request."})
            return

        if parsed.path == "/api/test":
            ok, err = imap_check(data.get("host", ""), data.get("port", 993),
                                 data.get("user", ""), data.get("password", ""))
            self._json(200, {"ok": ok, "error": err})
        elif parsed.path == "/api/save":
            self._json(200, self._save_account(data))
        elif parsed.path == "/api/password":
            self._json(200, self._set_password(data))
        elif parsed.path == "/api/delete":
            self._json(200, self._delete_account(data.get("name", "")))
        else:
            self._json(404, {"ok": False, "error": "not found"})

    # -- actions ----------------------------------------------------------

    def _save_account(self, data: dict) -> dict:
        name = (data.get("name") or "").strip()
        user = (data.get("user") or "").strip()
        password = data.get("password") or ""
        if not name or not user:
            return {"ok": False, "error": "Name and address are both required."}
        if not password:
            return {"ok": False, "error": "An app-specific password is required."}

        cfg = load_config()
        accounts = cfg.setdefault("accounts", [])
        if any(a["name"] == name for a in accounts):
            return {"ok": False, "error": f"An account named '{name}' already exists."}
        if any(a.get("user") == user for a in accounts):
            return {"ok": False, "error": f"{user} is already configured."}

        # Prove it works before writing anything, so a typo cannot leave a
        # broken account that only fails at 08:07.
        ok, err = imap_check(data.get("host", ""), data.get("port", 993), user, password)
        if not ok:
            return {"ok": False, "error": err}

        service = f"mail-digest-{name}"
        ok, err = keychain_store(service, user, password)
        if not ok:
            return {"ok": False, "error": f"Credentials work, but the Keychain refused them: {err}"}

        entry = {
            "name": name,
            "host": data.get("host", ""),
            "port": int(data.get("port") or 993),
            "user": user,
            "mailbox": data.get("mailbox") or "INBOX",
            "sent_mailbox": data.get("sent_mailbox") or "Sent",
            "drafts_mailbox": data.get("drafts_mailbox") or "Drafts",
            "smtp_host": data.get("smtp_host", ""),
            "smtp_port": int(data.get("smtp_port") or 587),
            "keychain_service": service,
            "role": data.get("role") or "personal",
        }
        aliases = {a["address"].strip().lower(): a.get("role") or "personal"
                   for a in (data.get("aliases") or []) if a.get("address", "").strip()}
        if aliases:
            aliases.setdefault(user.lower(), entry["role"])
            entry["alias_roles"] = aliases
        accounts.append(entry)
        save_config(cfg)
        return {"ok": True, "message": f"{name} verified and saved."}

    def _set_password(self, data: dict) -> dict:
        """Store a credential for an account that is already configured.

        Re-adding the account would work, but it would mean retyping every
        alias and role -- a good way to get one subtly wrong.
        """
        name = (data.get("name") or "").strip()
        password = data.get("password") or ""
        if not password:
            return {"ok": False, "error": "An app-specific password is required."}
        matches = [a for a in load_config().get("accounts", []) if a["name"] == name]
        if not matches:
            return {"ok": False, "error": f"No account named '{name}'."}
        account = matches[0]

        ok, err = imap_check(account.get("host", ""), account.get("port", 993),
                             account["user"], password)
        if not ok:
            return {"ok": False, "error": err}
        service = account.get("keychain_service") or f"mail-digest-{name}"
        ok, err = keychain_store(service, account["user"], password)
        if not ok:
            return {"ok": False, "error": f"Credentials work, but the Keychain refused them: {err}"}
        return {"ok": True, "message": f"{name} verified. Password stored as {service}."}

    def _delete_account(self, name: str) -> dict:
        cfg = load_config()
        before = len(cfg.get("accounts", []))
        cfg["accounts"] = [a for a in cfg.get("accounts", []) if a["name"] != name]
        if len(cfg["accounts"]) == before:
            return {"ok": False, "error": f"No account named '{name}'."}
        save_config(cfg)
        # The Keychain item is left alone on purpose: removing an account from
        # the digest should not silently destroy a credential you may still
        # want. Delete it yourself with `security delete-generic-password`.
        return {"ok": True, "message": f"Removed {name}. Its Keychain item was left in place."}


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mail digest setup</title>
<style>
  :root { --bg:#fbfaf8; --fg:#1b1b1a; --muted:#6b6a67; --line:#e2e0db;
          --card:#fff; --accent:#3a6b4f; --bad:#a23b2f; --good:#2f6b46; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16181a; --fg:#e8e6e1; --muted:#9a9793; --line:#2c2f33;
            --card:#1e2124; --accent:#7fb391; --bad:#e08072; --good:#7fb391; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.55
         -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  .wrap { max-width:760px; margin:0 auto; padding:32px 16px 80px; }
  h1 { font-size:24px; margin:0 0 4px; letter-spacing:-.01em; }
  h2 { font-size:16px; margin:32px 0 12px; }
  p.sub { color:var(--muted); margin:0 0 24px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:18px; margin-bottom:12px; }
  label { display:block; font-size:13px; color:var(--muted); margin:12px 0 4px; }
  input, select { width:100%; padding:9px 10px; border:1px solid var(--line);
         border-radius:7px; background:var(--bg); color:var(--fg); font-size:14px; }
  .row { display:flex; gap:10px; flex-wrap:wrap; }
  .row > div { flex:1 1 200px; }
  button { padding:9px 15px; border-radius:7px; border:1px solid var(--line);
           background:var(--card); color:var(--fg); font-size:14px; cursor:pointer; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .actions { display:flex; gap:8px; margin-top:18px; align-items:center; flex-wrap:wrap; }
  .msg { font-size:13px; }
  .msg.bad { color:var(--bad); } .msg.good { color:var(--good); }
  .acct { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }
  .acct small { color:var(--muted); display:block; margin-top:3px; }
  .tag { font-size:11px; border:1px solid var(--line); border-radius:99px;
         padding:1px 8px; color:var(--muted); margin-left:6px; }
  .alias { display:flex; gap:8px; margin-top:6px; }
  .alias input { flex:2; } .alias select { flex:1; }
  .note { font-size:12.5px; color:var(--muted); border-left:2px solid var(--line);
          padding-left:10px; margin-top:12px; }
  a { color:var(--accent); }
</style></head><body><div class="wrap">
<h1>Mail digest setup</h1>
<p class="sub">Runs on this Mac only. Passwords go straight to your Keychain &mdash; never to a file, and never back to this page.</p>

<h2>Accounts</h2>
<div id="accounts"></div>

<h2>Add an account</h2>
<div class="card">
  <label>Provider</label>
  <select id="provider"></select>
  <div id="phint" class="note"></div>

  <div class="row">
    <div><label>Short name (used on the command line)</label><input id="name" placeholder="work"></div>
    <div><label>Email address</label><input id="user" placeholder="you@example.com"></div>
  </div>

  <div class="row">
    <div><label>IMAP host</label><input id="host"></div>
    <div><label>Port</label><input id="port" value="993"></div>
  </div>
  <div class="row">
    <div><label>Sent folder</label><input id="sent_mailbox"></div>
    <div><label>Drafts folder</label><input id="drafts_mailbox"></div>
  </div>

  <label>Bundle this account's mail as</label>
  <select id="role"><option>personal</option><option>business</option><option>shopping</option></select>

  <div id="aliasBlock" style="display:none">
    <label>Aliases that land in this same inbox</label>
    <div class="note">Aliases need no password of their own. Giving each one a bundle is what lets a reply go out from the address it arrived at.</div>
    <div id="aliases"></div>
    <div class="actions"><button type="button" onclick="addAlias()">Add alias</button></div>
  </div>

  <label>App-specific password</label>
  <input id="password" type="password" autocomplete="off" placeholder="abcd efgh ijkl mnop">

  <div class="actions">
    <button type="button" onclick="test()">Test connection</button>
    <button type="button" class="primary" onclick="save()">Verify &amp; save</button>
    <span id="msg" class="msg"></span>
  </div>
</div>
<p class="note">When you are done, stop the server with Ctrl-C in the terminal that started it.</p>
</div>
<script>
const TOKEN = "__TOKEN__";
let PROVIDERS = [];

async function api(path, body) {
  const r = await fetch(path + "?token=" + encodeURIComponent(TOKEN), {
    method: body ? "POST" : "GET",
    headers: {"Content-Type": "application/json", "X-Setup-Token": TOKEN},
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

function el(id) { return document.getElementById(id); }

function renderAccounts(accounts) {
  const box = el("accounts");
  if (!accounts.length) {
    box.innerHTML = '<div class="card"><small>No accounts yet. Add one below.</small></div>';
    return;
  }
  box.innerHTML = accounts.map(a => {
    const aliases = Object.entries(a.alias_roles || {})
      .filter(([addr]) => addr !== (a.user || "").toLowerCase())
      .map(([addr, role]) => `${addr} <span class="tag">${role}</span>`).join("<br>");
    return `<div class="card"><div class="acct"><div>
      <strong>${a.name}</strong><span class="tag">${a.role || "personal"}</span>
      <small>${a.user}</small>
      ${aliases ? `<small style="margin-top:8px">${aliases}</small>` : ""}
    </div><button onclick="del('${a.name}')">Remove</button></div>
      <div class="alias" style="margin-top:12px">
        <input type="password" autocomplete="off" id="pw-${a.name}" placeholder="app-specific password">
        <button type="button" class="primary" onclick="setPw('${a.name}')">Set password</button>
      </div>
      <div class="msg" id="pwmsg-${a.name}" style="margin-top:6px"></div></div>`;
  }).join("");
}

function applyProvider() {
  const p = PROVIDERS.find(x => x.id === el("provider").value);
  if (!p) return;
  el("host").value = p.host; el("port").value = p.port;
  el("sent_mailbox").value = p.sent_mailbox; el("drafts_mailbox").value = p.drafts_mailbox;
  el("aliasBlock").style.display = p.supports_aliases ? "block" : "none";
  let hint = p.app_password_hint || "";
  if (p.app_password_url) hint += ` <a href="${p.app_password_url}" target="_blank" rel="noreferrer">Create one</a>`;
  el("phint").innerHTML = hint;
}

function addAlias() {
  const d = document.createElement("div");
  d.className = "alias";
  d.innerHTML = `<input placeholder="alias@example.com">
    <select><option>personal</option><option>business</option><option>shopping</option></select>
    <button type="button" onclick="this.parentNode.remove()">&times;</button>`;
  el("aliases").appendChild(d);
}

function collect() {
  const aliases = [...document.querySelectorAll("#aliases .alias")].map(r => ({
    address: r.querySelector("input").value, role: r.querySelector("select").value,
  })).filter(a => a.address.trim());
  return {
    name: el("name").value.trim(), user: el("user").value.trim(),
    host: el("host").value.trim(), port: el("port").value,
    sent_mailbox: el("sent_mailbox").value, drafts_mailbox: el("drafts_mailbox").value,
    role: el("role").value, aliases, password: el("password").value,
  };
}

function say(text, good) {
  const m = el("msg"); m.textContent = text; m.className = "msg " + (good ? "good" : "bad");
}

async function test() {
  say("Testing…", true);
  const r = await api("/api/test", collect());
  say(r.ok ? "Connection works." : r.error, r.ok);
}

async function save() {
  say("Verifying…", true);
  const r = await api("/api/save", collect());
  if (!r.ok) { say(r.error, false); return; }
  say(r.message, true);
  el("password").value = ""; el("name").value = ""; el("user").value = "";
  el("aliases").innerHTML = "";
  refresh();
}

async function setPw(name) {
  const field = el("pw-" + name), out = el("pwmsg-" + name);
  if (!field.value) { out.textContent = "Enter the password first."; out.className = "msg bad"; return; }
  out.textContent = "Verifying\u2026"; out.className = "msg good";
  const r = await api("/api/password", {name, password: field.value});
  out.textContent = r.ok ? r.message : r.error;
  out.className = "msg " + (r.ok ? "good" : "bad");
  if (r.ok) field.value = "";
}

async function del(name) {
  const r = await api("/api/delete", {name});
  say(r.ok ? r.message : r.error, r.ok);
  refresh();
}

async function refresh() {
  const s = await api("/api/state");
  PROVIDERS = s.providers;
  el("provider").innerHTML = PROVIDERS.map(p => `<option value="${p.id}">${p.label}</option>`).join("");
  el("provider").onchange = applyProvider;
  applyProvider();
  renderAccounts(s.accounts);
}
refresh();
</script></body></html>
"""


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/?token={TOKEN}"
    # flush explicitly: stdout is block-buffered when redirected to a file or
    # a pipe, and a setup tool whose URL never appears is useless.
    banner = (
        "Mail digest setup is running.\n"
        f"  {url}\n\n"
        "Loopback only -- nothing off this machine can reach it.\n"
        "Stop it with Ctrl-C when you are done.\n"
    )
    print(banner, flush=True)
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSetup server stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
