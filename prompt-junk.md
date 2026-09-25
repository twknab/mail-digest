Show me who is flooding my inbox and what we can do about each of them.

Run:

    python3 ~/mail-digest/mail_digest.py --junk-report --days 30

This scans both accounts for bulk mail only, groups it by sender, and works out
what leverage we have over each one. It reads nothing into my inbox and changes
nothing.

## What the recommendations mean

Each sender comes back with a `recommendation`. Present them grouped by that,
worst offenders first:

- **`one_click`** — supports RFC 8058 one-click unsubscribe. Safe to fire
  automatically; no browser, no tracking pixel, no confirmation page.
- **`mailto`** — unsubscribes by email. Safe, slightly slower to take effect.
- **`manual_link`** — has an unsubscribe page but no one-click header. Needs me
  to open it; you must not open it for me.
- **`hard_filter`** — either offers no unsubscribe at all, or already ignored
  one. Do not engage: unsubscribing from mail like this confirms my address is
  live. Filter it instead.
- **`keep`** — protected, because I have replied to them, flagged their mail, or
  listed them in contacts. Never propose removing these, however high the count.

Call out anything with `unsubscribe_ignored: true` first and separately. Those
senders were asked to stop more than two weeks ago and are still arriving —
they are the ones worth spending a filter on.

## What to give me

A short table: sender, count over the window, which account, and the
recommendation in plain words. Then tell me the total and roughly what share of
the 30 days' bulk mail the top few represent, so I can see whether killing five
senders fixes most of it.

Then propose a specific batch: the addresses you would act on now, and which
ones you would leave. Ask me to confirm.

## Acting on it, once I approve

Build the plan and show it to me before anything fires:

    python3 ~/mail-digest/junk_actions.py --from-report <report.json> \
      --address <one> --address <another> > plan.json

Then, and only after I say go:

    python3 ~/mail-digest/junk_actions.py --plan plan.json --execute

For `hard_filter` senders on **Gmail**, use the Gmail connector to create a real
server-side filter (skip inbox, delete) so the mail never arrives — that is
better than deleting it after the fact. For `hard_filter` senders on **iCloud**,
which has no rules API, tell me the exact rule to add at icloud.com → Mail →
Settings → Rules, and I will add it once.

Do not act on `manual_link`, `hard_filter`, or `keep` senders with the
unsubscribe tool. It will refuse them anyway, by design.
