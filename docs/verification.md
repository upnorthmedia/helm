# Live verification

What Helm was seen to do against a real firstmate home, as opposed to what the tests show. Each run records what the deck sent, what firstmate did, and how long each step took. Repositories other than Helm are not named here; the cases describe them by role.

## 2026-11-15: the simulator against a live home

The attended exit test from the Helm and firstmate alignment plan (task 6). The captain was at the desktop simulator; the bridge ran in `--live` against a real firstmate home with three local second mates. The physical deck was not used.

### Setup

- `scripts/run-sim.sh --home <firstmate home> --live -v`, then the bridge was restarted under a small wrapper (kept outside the repository) that logs, with timestamps, every deck event, every note the bridge sends, and every change to the result and `pending` fields of the models it sends. The wrapper only observes: the bridge code ran unchanged. A second read-only loop polled `fm-inbox.sh receipts` once a second.
- The home had the [YES rule](firstmate-setup.md) with the commit pin, the second mate routing line, and the quiet mode line. Posture was `present` for the whole run. The fleet ledger and the PR health monitor were on in every home.
- Bridge at `974ca19` (main when the run started).

### How the times were taken

- **Press to note**: from the key's `held` event (the end of the one second hold) to the bridge's `fm-inbox.sh note` returning.
- **Note to action**: from the note to firstmate's first visible act on it, which is a `resolved` line in the task's status when there is one, else the reply in `receipts`.
- **Action to deck**: from the reply's timestamp in `receipts` to the first model the bridge sent with that reply as its result. The bridge polls `receipts` every 5 s while a note waits, so this is 0 to 5 s by design.

The first two answers (cases 1 and 2) were pressed on the plain bridge before the logged one replaced it, so their press time is the note's own timestamp. The logged bridge took both notes back when it started (`after restart: 2 note(s) waiting`).

### Cases

| # | Case | What the deck sent | What firstmate did | Press to note | Note to action | Action to deck |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | LATER on a second mate's captain hold (listed in the primary) | `defer <task> / <key> until 2026-11-15.` | Routed it to the second mate, which re-held the item until 2026-11-15. The hold had been dated 2026-11-19, so the deferral got shorter (finding 2). | at the note | 152 s (reply) | never shown (finding 1) |
| 2 | YES on a second mate's PR, the run's real merge ask | YES, `merge <PR> at commit <40 character sha>`, `(second mate home <id>)` | Replied "Already done": the PR had been merged at that same commit 4 min 22 s before the press, while the deck still listed it as waiting (finding 3). | at the note | 130 s (reply) | never shown (finding 1) |
| 3 | YES on a second mate's decision that was a merge call | YES on `<task> / <key>`, with no home and no PR URL (the merge clause says "the PR it names") | Resolved the decision in the second mate's status and routed the captain's merge word to it. The second mate merged the PR 19 min 45 s after the press, once its checks were green. | 0.21 s | 55 s (resolved), 58 s (reply) | 1.4 s |
| 4 | YES on that same PR's item, shown before the second mate's summary had its captain row | YES, `merge <PR>` with no commit: the item was the fleet ledger's `pr_ready` stand-in, which has no head | Replied "Already routed" and changed nothing. | 0.22 s | 27 s (reply) | 4 s |
| 5 | Decision with a single recommendation (a worker's `needs-decision` with options A and B, B recommended) | YES on `<task> / <key>` | Recorded option B with `resolved [key=...]`, messaged the worker, and replied "Recorded: the single recommendation, option B". The item reached the deck 1 s after the worker raised it, through the fleet ledger. | 0.21 s | 50 s (resolved), 54 s (reply) | never shown (finding 1) |
| 6 | HOLD on a PR waiting on the captain, primary home, green, head known | `do not proceed on <task> / <key>. Raise it with me in chat.` | Did not merge, raised it in chat, replied "Held: ... will not be merged". | 0.20 s | 34 s (reply) | 4 s |
| 7 | YES on the same PR 30 s after the HOLD | YES, `merge <PR> at commit <sha>` | Did not merge. Replied that the YES came 30 s after a HOLD on the same PR and the change touches database access rules, and asked for confirmation in chat. The PR stayed open. | 0.21 s | 29 s (reply) | 5 s |

Firstmate drained the inbox in two batches: cases 1 to 3 were answered together at 00:19:57Z, and cases 5 and 6 together at 00:55:33Z. Case 7 came 25 s after that second batch. Every note was acknowledged and answered in the same receipts read, so the deck never showed "Seen" before the reply. No note waited the 180 s that would trigger the stall hint.

### What this run verified

- **Notes are fast and exact.** A held key became one `fm-inbox.sh note` within 0.22 s every time, with the request id and text the bridge README describes, including the commit pin on PR items whose head was known.
- **Firstmate acts on deck notes, in this home, within a minute or so.** It took 27 to 152 s from note to reply. Every action matched the home rule: a single recommendation was recorded, a HOLD stopped a merge and went to chat, a LATER re-held the item, and nothing merged that should not have.
- **Second mate routing works end to end.** YES on a second mate's merge call was routed from the primary, not answered there. The second mate merged the PR once its checks passed. A note on a second mate's PR item names that home. A second mate's decision is listed under the primary (its task is the second mate itself), so its note names no home; firstmate routed it by the task name anyway.
- **Contradicting answers were caught by firstmate.** A YES 30 s after a HOLD on the same PR was not merged; firstmate asked in chat instead.
- **Replies reach the deck within the poll interval** (1.4 to 5 s), and a reply clears the item's `pending` marker.
- **Pending notes survive a bridge restart.** The restarted bridge took back the two notes still waiting.

### Findings (not fixed here)

1. **Only one reply reaches the result screen when several land at once.** The result slot holds one result. In both batches, firstmate replied to several notes in the same drain, and the deck showed only one of them: three of the seven replies were never shown. They are in `receipts` and cleared `pending`, so nothing was lost, but the captain did not see them on the deck.
2. **LATER can shorten a deferral.** LATER names tomorrow's date. On a hold already deferred to a later date, firstmate followed the note literally and moved the hold earlier. Either the note should say "not before" or the bridge should skip the date when the hold's `hold_until` is already later.
3. **A merged PR can still show as waiting.** A second mate's summary listed a PR as "merge approval needed" minutes after it merged, so the captain held YES on a merged PR. Firstmate replied "already done", which is harmless, but the deck showed stale state.
4. **A YES after a HOLD is not linked.** A HOLD or LATER after a YES names the YES it replaces, but a YES after a HOLD says nothing about the HOLD. Firstmate noticed on its own (case 7); the note could say so.
5. **A ledger stand-in PR item takes an unpinned YES.** Until the second mate's summary carries its captain row, the PR item has no head and the YES names the URL only. This is the documented behavior; the run shows it happens in practice, not only in theory.
6. **`pending` flickered** off and on for an item while summaries republished.
7. **The bridge logs no key, note, or reply at INFO.** Timing this run needed a wrapper. A `-v` line per note sent and per reply received would make the next run, and any support question, a log read.

### Still not verified

- A merge done by the primary itself through `fm-pr-merge.sh --expected-head` on a deck YES. The primary's only merge ask (case 7) was refused because of the HOLD before it, and the run's real merge ask (case 2) was already merged.
- A YES refused because the PR moved after the hold (no push landed during the run).
- "Seen" and "firstmate has not picked this up" on a live home: firstmate read and answered every note in one step, and none waited 3 minutes.
- Whether a note wakes firstmate in quiet mode: posture was `present` throughout.
- Anything on the physical deck, and remote second mates (none in this home).
