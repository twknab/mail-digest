# Mail digest — setup

Three weekday digests of the mail that actually needs you, across every account
you own, plus reply drafts and a junk report that gets shorter over time.

Everything runs on your Mac. Nothing is uploaded, no password is ever written
to a file, and the reader is strictly read-only — it opens mailboxes with
`readonly=True` and fetches with `BODY.PEEK`, so **running it never marks
anything as read**.

Requires macOS (for the Keychain) and Python 3.9+. There are no dependencies to
install; everything used is in the standard library.

## 1. Put the folder in place

It works from anywhere — the scripts resolve their own location:

```bash
cd /path/to/mail-digest && chmod +x *.sh
```

State lives in `~/.mail-digest/`, deliberately outside the code directory, so
your saved position and contacts survive a `git clean` and never land in a
commit.

## 2. Create an app-specific password per login

Your normal password will not work. Providers require an app-specific password
for IMAP, and generally require two-factor authentication to be on first.

**One password per login, not per address.** If your provider supports aliases
(iCloud, Fastmail and others), every alias delivers into the same INBOX behind
a single login and needs nothing of its own.

The setup UI in the next step links to the right page for whichever provider
you pick, and tells you what that provider expects.

## 3. Run the setup UI

```bash
python3 setup_server.py
```

It prints a `http://127.0.0.1:…` URL and opens it. Pick your provider, and the
host, port and folder names fill themselves in. Add the address, name any
aliases and choose which bundle each belongs to, paste the app password, and
press **Verify & save**.

It logs in before it saves anything, so a typo fails here rather than silently
at 08:07. On success the password goes into your login Keychain and the account
into `accounts.json`.

The server binds to **127.0.0.1 only**, requires a random token minted at
startup, and never sends a password back to the page or writes one to disk.
Stop it with Ctrl-C when you are done.

Repeat for each account. To check what it wrote:

```bash
python3 -c "import json;print(json.dumps(json.load(open('accounts.json')),indent=2))"
```

### Using 1Password instead

If you keep app passwords in 1Password, store each one as a Password item named
after its Keychain service (`mail-digest-<account name>`) and run:

```bash
./sync-credentials.sh
```

1Password stays the source of truth; the Keychain is a delivery cache. The
scheduled run cannot satisfy a biometric prompt at 08:07, so it reads the
Keychain and never talks to 1Password at all. Re-run that script after rotating
a password.

## 4. Adding a provider

Providers are data, not code. `providers.json` declares host, port, folder
names, whether aliases share one inbox, and where to create an app password.
Add an entry and it appears in the setup UI — no Python change needed. Anything
IMAP works via the **Other IMAP server** option.

## 5. Test it, carefully

```bash
python3 mail_digest.py --no-save --since-hours 2
```

`--no-save` means the saved position does not move, so run it as often as you
like. Add `--account <name>` to check one.

**Then do the check that matters most** — that a run marks nothing as read:

```bash
python3 check_readonly.py > /tmp/before.json
python3 mail_digest.py --no-save --since-hours 24 > /dev/null
python3 check_readonly.py --compare /tmp/before.json
```

It must print PASS. This counts `UNSEEN` over IMAP rather than asking you to
eyeball a mailbox, which would miss a single message flipping. A reader that
silently marks mail read is worse than no reader at all.

## 6. Tell it who matters

```bash
mkdir -p ~/.mail-digest
cat > ~/.mail-digest/contacts.txt <<'EOF'
# One address or domain per line. Never filtered as bulk, never proposed
# for removal in the junk report.
partner@example.com
yourcompany.com
EOF
```

Optional, but the single biggest lever on digest quality.

## 7. Bundles

Each account carries a `role` — `business`, `personal` or `shopping` — and the
digest is grouped by it.

Where a provider supports aliases, several addresses share **one** INBOX, so
the account cannot say which identity a message belongs to. `alias_roles` maps
each alias to a bundle, matched against `Delivered-To`, `X-Original-To`, `To`
and `Cc`.

`shopping` is treated as guilty until proven innocent: only a failed delivery,
fraud alert, refund or missing order surfaces; promotions never do.

## 8. Run a real digest by hand

```bash
claude -p "$(sed "s|~/mail-digest|$PWD|g" prompt-digest.md)" \
  --allowedTools "Bash(python3 $PWD/mail_digest.py:*)"
```

(The `sed` expands `~` — `--allowedTools` matches a literal path prefix, so a
bare `~` would not match and the run would stall asking permission.)

If that reads well, install the schedule:

```bash
./install.sh
launchctl kickstart -k gui/$(id -u)/local.mail-digest   # fire one now
```

Set `MAIL_DIGEST_LABEL` before `./install.sh` if you want a different launchd
label. Digests land in `digests/`, and you get a notification only when
something needs you.

## 9. Drafting a reply

The digest ends each actionable item with a draft handle. Feed it to:

```bash
python3 mail_reply.py --account work --uid 4821 --body-file reply.txt
```

That prints the draft without writing it. Add `--append` to save it into that
account's Drafts folder, where you review it and press Send yourself.

The reply goes out **from the address it was delivered to** — answering mail
sent to a work alias from your personal address leaks that address to a work
contact. `mail_reply.py` has no SMTP capability at all, so nothing it produces
can leave your outbox without you. See `SPEC-replies.md`.

## 10. The junk pass

Do this one interactively:

```bash
sed "s|~/mail-digest|$PWD|g" prompt-junk.md | pbcopy
claude   # then paste
```

You get a ranked table of who is flooding you, with a recommendation each.
Nothing fires until you approve a specific batch, and the tool refuses to
"unsubscribe" from anything that looks like spam — for those, engaging just
confirms your address is live, so we filter instead.

## Files

| Path | What it is |
| --- | --- |
| `setup_server.py` | Local browser setup UI. Loopback only. |
| `providers.json` | Provider presets. Add one here, not in code. |
| `mail_digest.py` | The reader. Read-only, all accounts, JSON out. |
| `check_readonly.py` | Proves a run changes no unread count. |
| `mail_reply.py` | Drafts a reply into Drafts. Dry run unless `--append`. Cannot send. |
| `SPEC-replies.md` | Why drafting works the way it does. |
| `junk_actions.py` | Unsubscribe executor. Dry run unless `--execute`. |
| `sync-credentials.sh` | Copies app passwords from 1Password into the Keychain. |
| `run-digest.sh` | Scheduled entry point: run, save, notify. |
| `accounts.json` | Your accounts. Never committed. No passwords. |
| `~/.mail-digest/state.json` | Last-seen message per account. |
| `~/.mail-digest/contacts.txt` | People who are never filtered. |

## Tests

```bash
for t in test_mail_digest test_junk_actions test_mail_reply test_setup_server; do
  python3 $t.py || break
done
```

141 checks covering unsubscribe parsing, bulk detection, sender classification,
role and alias routing, reply threading and From-alias selection, the setup
server's token gate and validation, and the safety refusals. No network or
mailbox needed.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `missing_credentials` | Keychain item name or address does not match `accounts.json`. |
| `login_failed` | App password wrong, or 2FA not enabled on the account. |
| `select_failed` | Folder name differs; localised accounts rename Sent/Drafts. |
| Nothing at 08:07 | `cat launchd.err.log` and `digest.log` in this folder. |
| Keychain prompt at run time | Re-add the item with `-T /usr/bin/security`. |
| Digest repeats old mail | `~/.mail-digest/state.json` was deleted; it resyncs next run. |
