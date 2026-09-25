#!/usr/bin/env python3
"""Render a digest as a standalone HTML page and open it.

    python3 viewer.py              # newest digest
    python3 viewer.py --list       # index of every past digest
    python3 viewer.py <file.md>

No server and no dependencies: it writes a self-contained file and hands it to
the browser. The digest format is narrow enough that a purpose-built renderer
beats taking on a markdown library.
"""

from __future__ import annotations

import argparse
import html
import re
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIGESTS = HERE / "digests"
VIEW_DIR = Path.home() / ".mail-digest" / "view"

CSS = """
:root{--bg:#faf9f7;--fg:#1c1c1b;--muted:#6f6e6a;--line:#e5e3de;--card:#fff;
--accent:#c2703d;--ok:#3f7d58;--chip:#f1efea;--shadow:0 1px 2px rgba(0,0,0,.04)}
@media (prefers-color-scheme:dark){:root{--bg:#141618;--fg:#e9e7e2;--muted:#94918c;
--line:#282c30;--card:#1c1f22;--accent:#e09055;--ok:#7fb391;--chip:#23272b;
--shadow:0 1px 2px rgba(0,0,0,.3)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:720px;margin:0 auto;padding:48px 20px 96px}
header{margin-bottom:36px;padding-bottom:20px;border-bottom:1px solid var(--line)}
h1{font-size:15px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
color:var(--muted);margin:0 0 8px}
.when{font-size:27px;font-weight:600;letter-spacing:-.02em;margin:0}
.count{display:inline-flex;align-items:center;gap:7px;margin-top:14px;font-size:14px;
padding:5px 13px;border-radius:999px;background:var(--chip);color:var(--muted)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok)}
.count.active{color:var(--accent)}.count.active .dot{background:var(--accent)}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:22px 24px;margin-bottom:16px;box-shadow:var(--shadow)}
.inbox{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.inbox .addr{font-size:16px;font-weight:600;letter-spacing:-.01em}
.role{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
border:1px solid var(--line);border-radius:999px;padding:2px 9px}
.bucket{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;
color:var(--muted);margin:22px 0 10px}
.bucket.act{color:var(--accent)}
.item{padding:14px 0;border-top:1px solid var(--line)}
.item:first-of-type{border-top:none}
.item .who{font-weight:600}
.item ul{margin:7px 0 0;padding-left:17px}
.item li{margin:3px 0}
.item strong{font-weight:600}
.fyi{opacity:.72}
code,.draft{font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
.draft{display:block;margin-top:9px;background:var(--chip);border-radius:7px;
padding:8px 11px;color:var(--muted);user-select:all;word-break:break-all}
p.plain{color:var(--muted)}
.empty{text-align:center;color:var(--muted);padding:56px 0}
.idx a{display:flex;justify-content:space-between;gap:12px;padding:11px 2px;
border-bottom:1px solid var(--line);text-decoration:none;color:var(--fg)}
.idx a:hover{color:var(--accent)}
.idx .n{color:var(--muted);font-size:13px}
.rule{height:1px;background:var(--line);margin:28px 0 20px;border:0}
footer{margin-top:32px;text-align:center;color:var(--muted);font-size:12.5px}
a{color:var(--accent)}
:root{--icon-bg:#eceae5;--icon-fg:#3c3a36;--icon-accent:#c2703d}
@media (prefers-color-scheme:dark){:root{--icon-bg:#23272b;--icon-fg:#d9d6d1;--icon-accent:#e09055}}
.about{text-align:center;padding:54px 0 24px}
.abouttitle{font-size:26px;font-weight:600;letter-spacing:-.02em;margin:18px 0 6px}
.tagline{color:var(--muted);margin:0 0 30px}
.facts{text-align:left;max-width:460px;margin:0 auto;border-top:1px solid var(--line);padding-top:22px}
.facts p{font-size:14.5px;color:var(--muted);margin:0 0 14px}
.by{margin-top:34px;color:var(--muted);font-size:13px}
"""


def inline(text: str) -> str:
    """Escape, then re-apply the handful of inline marks the digest uses."""
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`(.+?)`", r"<code>\1</code>", out)
    out = re.sub(r"(?<![\w@.])((?:https?://)[^\s<]+)", r'<a href="\1">\1</a>', out)
    return out


def render_digest(path: Path) -> str:
    lines = path.read_text().splitlines()
    title, count, body, bucket, open_item, open_list = "", None, [], "", False, False

    def close_item():
        nonlocal open_item, open_list
        if open_list:
            body.append("</ul>")
            open_list = False
        if open_item:
            body.append("</div>")
            open_item = False

    def close_section():
        close_item()
        if body and "<section>" in "".join(body[-40:]):
            body.append("</section>")

    sections_open = False
    for raw in lines:
        line = raw.rstrip()
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        m = re.match(r"^ACTION_ITEMS:\s*(\d+)", line)
        if m:
            count = int(m.group(1))
            continue
        if line.startswith("### "):
            close_item()
            if sections_open:
                body.append("</section>")
            heading = line[4:].strip()
            addr, _, role = heading.partition("—")
            body.append("<section><div class='inbox'>"
                        f"<span class='addr'>{html.escape(addr.strip())}</span>"
                        + (f"<span class='role'>{html.escape(role.strip())}</span>" if role.strip() else "")
                        + "</div>")
            sections_open = True
            bucket = ""
            continue
        if re.match(r"^\*\*Needs action\*\*$", line):
            close_item(); bucket = "act"
            body.append("<div class='bucket act'>Needs action</div>"); continue
        if re.match(r"^\*\*Worth knowing\*\*$", line):
            close_item(); bucket = "fyi"
            body.append("<div class='bucket'>Worth knowing</div>"); continue
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", line.strip()):
            close_item()
            if sections_open:
                body.append("</section>")
                sections_open = False
            body.append("<div class='rule'></div>")
            continue
        if line.startswith("draft:") or line.startswith("- draft:"):
            text = line.split("draft:", 1)[1].strip()
            if open_list:
                body.append("</ul>"); open_list = False
            body.append(f"<span class='draft'>mail_reply.py {html.escape(text)}</span>")
            continue
        # A bolded name on its own line, or "- **Who:** ..." starts an item.
        if re.match(r"^\*\*[^*]+\*\*(\s*\(.+\))?$", line):
            close_item()
            cls = "item fyi" if bucket == "fyi" else "item"
            body.append(f"<div class='{cls}'><div class='who'>{inline(line)}</div>")
            open_item = True
            continue
        if line.startswith("- "):
            if not open_item:
                cls = "item fyi" if bucket == "fyi" else "item"
                body.append(f"<div class='{cls}'>")
                open_item = True
            if not open_list:
                body.append("<ul>"); open_list = True
            body.append(f"<li>{inline(line[2:])}</li>")
            continue
        if line:
            close_item()
            body.append(f"<p class='plain'>{inline(line)}</p>")

    close_item()
    if sections_open:
        body.append("</section>")

    inner = "\n".join(body)
    if not inner.strip():
        inner = "<div class='empty'>Nothing needed you this run.</div>"

    if count is None:
        pill = "<span class='count active'><span class='dot'></span>no item count reported</span>"
    elif count > 0:
        word = "item" if count == 1 else "items"
        pill = f"<span class='count active'><span class='dot'></span>{count} {word} need you</span>"
    else:
        pill = "<span class='count'><span class='dot'></span>all caught up</span>"

    when = html.escape(title.replace("Mail digest — ", "")) or path.stem
    return page(f"Digest · {when}", f"""
<header><h1>Mail digest</h1><p class='when'>{when}</p>{pill}</header>
{inner}
<footer><a href='index.html'>All digests</a></footer>""")



# A digest is mail distilled: the envelope is the source, the three bars
# beneath it are what is left after triage -- fewer, shorter, ranked.
ICON = """<svg viewBox='0 0 64 64' width='72' height='72' role='img' aria-label='Mail Digest'>
  <rect x='2' y='2' width='60' height='60' rx='15' fill='var(--icon-bg)'/>
  <path d='M14 17h36a3 3 0 0 1 3 3v13a3 3 0 0 1-3 3H14a3 3 0 0 1-3-3V20a3 3 0 0 1 3-3z'
        fill='none' stroke='var(--icon-fg)' stroke-width='3' stroke-linejoin='round'/>
  <path d='M11.5 20.5 32 32l20.5-11.5' fill='none' stroke='var(--icon-fg)'
        stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>
  <rect x='16' y='43' width='32' height='3.4' rx='1.7' fill='var(--icon-accent)'/>
  <rect x='20' y='49' width='24' height='3.4' rx='1.7' fill='var(--icon-accent)' opacity='.7'/>
  <rect x='25' y='55' width='14' height='3.4' rx='1.7' fill='var(--icon-accent)' opacity='.45'/>
</svg>"""


def render_about() -> str:
    return page("About Mail Digest", f"""
<div class='about'>
  {ICON}
  <h2 class='abouttitle'>Mail Digest</h2>
  <p class='tagline'>Three weekday digests of the mail that actually needs you.</p>
  <div class='facts'>
    <p>Runs entirely on this Mac. Nothing is uploaded and no password is written
       to a file.</p>
    <p>The reader is read-only by construction: mailboxes open
       <code>readonly=True</code> and every fetch uses <code>BODY.PEEK</code>,
       so a run never marks anything as read.</p>
    <p>Replies are drafted into your Drafts folder and never sent \u2014 the
       drafting module holds no SMTP capability at all.</p>
  </div>
  <p class='by'>Built by <a href='https://timknab.dev'>timknab.dev</a></p>
</div>""")


def render_index(files: list[Path]) -> str:
    rows = []
    for f in files:
        c = re.search(r"^ACTION_ITEMS:\s*(\d+)", f.read_text(), re.M)
        n = int(c.group(1)) if c else None
        label = "no count" if n is None else ("all caught up" if n == 0
                                             else f"{n} need{'s' if n == 1 else ''} you")
        rows.append(f"<a href='{f.stem}.html'><span>{f.stem}</span>"
                    f"<span class='n'>{label}</span></a>")
    return page("All digests", "<header><h1>Mail digest</h1><p class='when'>All runs</p></header>"
                f"<section class='idx'>{''.join(rows) or 'No digests yet.'}</section>")


def page(title: str, inner: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body><div class='wrap'>{inner}</div></body></html>")


def main() -> int:
    p = argparse.ArgumentParser(description="Render a digest as HTML and open it.")
    p.add_argument("file", nargs="?", type=Path)
    p.add_argument("--list", action="store_true", help="render the index of all digests")
    p.add_argument("--about", action="store_true", help="render the about page")
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args()

    VIEW_DIR.mkdir(parents=True, exist_ok=True)
    if args.about:
        target = VIEW_DIR / "about.html"
        target.write_text(render_about())
        print(target)
        if not args.no_open:
            webbrowser.open(target.as_uri())
        return 0

    files = sorted(DIGESTS.glob("*.md"), reverse=True)
    if not files:
        print("No digests yet.")
        return 1

    # Always refresh the index so its links resolve.
    for f in files[:60]:
        (VIEW_DIR / f"{f.stem}.html").write_text(render_digest(f))
    (VIEW_DIR / "index.html").write_text(render_index(files[:60]))

    target = VIEW_DIR / ("index.html" if args.list else f"{(args.file or files[0]).stem}.html")
    print(target)
    if not args.no_open:
        webbrowser.open(target.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
