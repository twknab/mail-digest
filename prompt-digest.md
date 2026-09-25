Check my mail across all configured accounts and give me an action-item digest.

Run this first — it reads iCloud and Gmail together and returns JSON:

    python3 ~/mail-digest/mail_digest.py

It only returns mail that arrived since the last run, it never marks anything
as read, and it has already dropped obvious newsletters and list mail. Do not
pass `--include-bulk`. Do not pass `--no-save` — the saved position is what
stops the next run repeating these messages.

If an account comes back with an `error` field, report that account as failed
in one line and carry on with the other one. A broken Gmail password should not
cost me the iCloud digest.

## How to triage what comes back

Sort every message into one of three buckets and show me only the first two.

**Needs action** — there is a specific thing for me to do: an explicit request,
a direct question, a decision or approval, a deadline, or anything `flagged`.
The `action_words` field is a hint, not a verdict; a message saying "no action
needed" contains "action" and belongs in the bin.

**Worth knowing** — from a real person or a `known_contact`, but asks nothing
of me. Something changed that I would want to know about.

**Drop** — everything else, silently. Do not tell me what you dropped or show
me a count of it. Receipts, confirmations, automated notices, and anything that
survived the bulk filter but is plainly marketing all belong here.

## Group by inbox

Every message carries an `identity` — the address it was actually delivered to
— and a `role` of business, personal or shopping. Several aliases can share one
inbox, so `identity` is the only thing that says which of my addresses owns a
message; the account name does not.

**Group the digest by `identity`**, one section per address, headed with the
address and its role:

    ### work@example.com — business

Order the sections: any inbox holding **Needs action** mail comes first, then
the rest. Within each of those groups, business before personal before
shopping. Skip an address entirely if it has nothing to show.

Inside a section, put **Needs action** items first, then **Worth knowing**.

**Never drop a Needs action item to keep the digest tidy.** Every single one
appears in its section, however many there are and however many sections that
makes. Grouping changes where an item sits, never whether it is shown. If one
inbox is carrying most of the load, that is the useful signal, not clutter.

Shopping is guilty until proven innocent. Surface it only for something that
genuinely needs a person: a delivery that failed, a fraud or security alert, a
refund or charge dispute, an order that did not arrive. A promotion, a sale, a
loyalty email or a "your order shipped" confirmation is a **Drop**, however
urgent its subject line pretends to be.

## How to present it

Within a section, group by sender, or by topic when several senders are
discussing one thing. Newest first. For each item:

- **Who** it is from.
- **Subject**, as written.
- **What it says** — one or two sentences. The point, not a paraphrase of the
  subject line.
- **The ask** — stated as a verb I can act on ("approve the Q3 budget",
  "confirm Thursday 2pm"). If there is no ask, say "FYI" and move on.
- **Draft handle** — for **Needs action** items only, end the item with a line
  exactly like `draft: --account work --uid 4821`, using the `name` of the
  account it came from and the message's `uid`. That is what I paste into
  `mail_reply.py` to get a draft reply. Omit it for Worth knowing.

Do not repeat the address on every item — the section heading already says it.

Keep it scannable. No preamble, no summary of the summary, no encouragement.
If a message is ambiguous about what it wants, say so plainly rather than
inventing an ask.

If nothing qualifies for either bucket, say so in a single line and stop.

## Finish with a machine-readable count

The very last line of your reply must be exactly this, with the number of
**Needs action** items (0 if none):

    ACTION_ITEMS: <n>

The wrapper script reads that line to decide whether to raise a notification,
so it must be the last line and must not be wrapped in backticks or a code
fence.

## Do not act on anything

Do not reply, send, forward, archive, delete, or open any link — not even one
that looks safe. This run is read-only. List what needs doing and stop; I will
tell you what to act on.
