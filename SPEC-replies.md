# Spec — drafting replies

## Summary

The digest tells me what needs an answer. This adds the next step: turn a
message that needs a reply into a **draft**, sitting in the right account's
Drafts folder, threaded correctly and sent from the right address — so I open
Mail, read it, and press Send myself.

## Decisions already made

- **Drafts only.** Nothing is ever transmitted by this tool. The single write
  it performs is `APPEND` into a Drafts mailbox. A bad draft is deleted; a bad
  send is not recallable.
- **On request, not on schedule.** The 3×-daily digest stays read-only. Drafting
  is a separate command, so no drafts pile up unasked.

## The rule that matters most: reply from the right address

On providers that support them, several aliases share **one** INBOX behind a
single login. A business message arrives at the work alias; replying from the
account's primary address leaks a personal address to a work contact and looks
wrong to the recipient.

So the `From` is chosen from the message's own delivery headers
(`Delivered-To`, `X-Original-To`, `To`, `Cc`) — the same signal that already
decides business/personal/shopping — and only falls back to the account's
primary address when no alias matches.

## Threading

A reply that does not thread is a new conversation in the recipient's client.
Required: `In-Reply-To` set to the original `Message-ID`, `References`
carrying the original chain plus that `Message-ID`, and `Re:` applied once.
`Reply-To` wins over `From` when choosing the recipient.

## Safety

- The INBOX is opened `readonly=True` and read with `BODY.PEEK`, so drafting a
  reply must not change an unread count any more than reading did.
- Dry run by default. `--append` is required to write the draft, mirroring
  `junk_actions.py --execute`.
- No SMTP. This tool holds no send capability at all, by construction.

## Acceptance criteria

- [ ] A reply to mail delivered to an alias is `From` that alias.
- [ ] `In-Reply-To` and `References` are set; `Re:` is not doubled.
- [ ] The draft appears in the right Drafts folder, flagged `\Draft`.
- [ ] Unread counts are unchanged after drafting.
- [ ] Without `--append`, nothing is written anywhere.

## Out of scope

- Sending. Deliberately.
- Auto-drafting on the schedule.
- Deciding *what to say* — the body is supplied to this tool, not invented by it.
