# Setting up firstmate for Helm

Helm reads a [firstmate](https://github.com/kunchenguid/firstmate) home and writes one kind of record into it: a captain inbox note, through `bin/fm-inbox.sh note`. Everything else on this page is optional, and each piece you skip costs the deck something specific, listed below.

To see what your home already has, run the doctor from your Helm checkout:

```sh
python3 -m helm.bridge --doctor --home /path/to/firstmate   # or set FM_HOME
```

It prints one line per check (`ok`, `warn`, or `missing`) with the fix, and exits nonzero only when a required piece is missing. It only reads: it runs the bridge's own read commands, reads files, and looks programs up on `PATH`. More under [The doctor](#the-doctor).

## What each piece costs

| Piece | Needed? | Without it |
| --- | --- | --- |
| A firstmate home with `state/` and `bin/fm-inbox.sh` | Required | Nothing works. Point `--home` (or `FM_HOME`) at the checkout firstmate runs from. |
| `fm-inbox.sh ready` (`fm-primary-ready.v1`) with `can_receive` true | Required | The deck shows its link as unknown, and a held key's note waits until firstmate can receive. |
| `state/home-summary.json` (`fm-secondmate-home-summary.v1`) in the primary | Required | No items, counts, or PRs. Firstmate publishes it whenever it runs. |
| [The YES rule](#the-yes-rule) in `data/captain.md` | Your choice | A held YES is a plain note, not your approval: firstmate reads it and asks you in chat. LATER and HOLD still reach firstmate as notes. |
| `config/fleet-ledger` in each home | Recommended | A new item shows only when firstmate next republishes that home's summary, not when the event happens. |
| `config/pr-health-monitor` in each home that owns PRs | Recommended | The deck cannot tell that a PR has failing checks or conflicts, so YES is not dimmed for it. Firstmate's merge guards still refuse such a PR. |
| herdr | Optional | SHOW ME cannot bring a pane forward, and there is no herdr line or context gauge. SHOW ME still opens a board, report, or PR. |
| The usagebar plugin for herdr | Optional | The context gauge reads unknown. |
| `quota-axi`, with the Keychain step on macOS | Optional | The usage gauge reads unknown, and the calm light bar shows no gauge lights. |
| `lavish-axi` | Optional | SHOW ME opens a PR, but no review board or report. |

## The YES rule

**This rule is your own opt-in grant. It is not firstmate's default.** Out of the box, firstmate treats a note from an outside bridge as a message, not as your approval: it does not merge a PR or answer a decision on a note alone. Helm's YES key does what the README describes only after you add the rule below to your own firstmate home. Without it, the deck still works; YES just becomes a request firstmate confirms with you in chat.

What you are granting: firstmate takes a note that begins with the deck's exact YES words as your current, explicit word for the one PR or decision it names. Helm writes that note only after a one second hold with the item on screen, but firstmate cannot tell who wrote a note: any program running as your user could write one with the same words. The rule keeps the damage of a forged note small. It covers one named PR at one named commit, merged only through firstmate's normal guards, or one decision where firstmate gave a single recommendation, and nothing destructive.

### Where it goes

Paste the block below into `data/captain.md` in your **primary** firstmate home: the local, gitignored file of captain preferences that firstmate reads at every session start. Helm sends notes only to the primary, so second mate homes do not need it. Keep the quoted opening words exactly as written; they are the words the deck writes, byte for byte, and the doctor looks for them. Firstmate reads the file at its next session start.

### The rule

```markdown
## Helm deck notes

My Helm deck writes captain inbox notes through `bin/fm-inbox.sh note`. This rule is my own opt-in grant, not firstmate's default.

- A captain inbox note that begins exactly "Captain, from the Helm deck, held to confirm: YES" is my current, explicit word for exactly the one task, key, and PR it names, and nothing broader:
  - If it is a merge ask, merge only that PR, through `bin/fm-pr-merge.sh` under its normal guards (open, not a draft, mergeable, no conflicts, green at the live head). Never waive a red or pending check on a deck note, and never merge any other PR.
  - When the note names a commit ("at commit <sha>"), pass it to `bin/fm-pr-merge.sh` as `--expected-head <sha>`. If the PR's live head differs, do not merge, and reply that the PR changed since I held YES.
  - If it is not a merge ask, and you gave exactly one recommended option for that decision, record that option as my answer through your normal answer path (`bin/fm-captain-hold.sh answer` for a captain hold). If you gave several options or none, change nothing and reply.
  - If the note names a second mate home, do not merge or answer from this home. Route my words, including any commit, to that second mate as my answer for its task, and reply saying you routed it.
- A note that begins "Captain, from the Helm deck: defer" re-holds that item until the date it names (`--until <date>`).
- A note that begins "Captain, from the Helm deck: do not proceed" means do not proceed on that item. Raise it with me in chat.
- Destructive, irreversible, or security-sensitive actions always need me in chat. A deck note never covers them.
- Quiet mode does not suspend this rule: I am present, so handle deck notes as usual.
- Always reply to every deck note with `bin/fm-inbox.sh reply <id>`, saying what you did or why not, so the deck can show it.
```

### What the deck sends

These are the notes the rule answers. The bridge builds them from a closed list, so the deck can never send free text. Each carries a request id, so pressing again the same day replays the first note instead of sending a second one.

| Key | Note |
| --- | --- |
| YES on a PR | ``Captain, from the Helm deck, held to confirm: YES on `<task>` / `<key>`. If this is a merge ask, merge `<PR URL>` at commit `<40 character sha>` under your normal checks. Otherwise go with your single recommended option, only if you gave exactly one. If neither applies, change nothing and reply.`` |
| YES on a decision | The same, naming "the PR it names" instead of a URL and commit. |
| LATER | ``Captain, from the Helm deck: defer `<task>` / `<key>` until 2026-11-12.`` (the next local date) |
| HOLD | ``Captain, from the Helm deck: do not proceed on `<task>` / `<key>`. Raise it with me in chat.`` |

An item from a second mate adds ``(second mate home `<id>`)`` after the task and key. The bridge's own description is in [helm/bridge/README.md](../helm/bridge/README.md).

## The fleet ledger, in each home

The ledger is firstmate's documented hook for outside readers ([docs/fleet-ledger.md](https://github.com/kunchenguid/firstmate/blob/main/docs/fleet-ledger.md) in firstmate). Helm uses it to show a new item the moment a worker reports it, instead of when the summary next republishes.

- Turn it on by creating the flag in each home Helm reads: the primary and every local second mate home listed in its `data/secondmates.md`.

  ```sh
  touch /path/to/firstmate/config/fleet-ledger
  ```

  The flag is per home and is not inherited by second mate homes.
- Firstmate never rotates `state/fleet-ledger.jsonl`: it grows with every status line any task writes. Truncate it now and then:

  ```sh
  : > /path/to/firstmate/state/fleet-ledger.jsonl
  ```

  The bridge notices the truncation and keeps reading from the start of the empty file. The doctor warns when a ledger passes 50 MB.
- The ledger copies status text verbatim from the home's `state/`, so give anything that reads it the trust you give `state/`.

## The PR health monitor

`config/pr-health-monitor` opts a home into firstmate's monitor of the PRs it owns. It records failing checks and conflicts in `state/pr-health.json`, which the deck reads to keep YES dark on a PR known to be red or conflicted. Create the flag in each home that owns PRs:

```sh
touch /path/to/firstmate/config/pr-health-monitor
```

It takes effect at firstmate's next session start, or right away after `bin/fm-pr-health.sh arm`. Like the ledger flag, it is per home and not inherited. Without it, firstmate still refuses to merge a red PR; the deck just cannot warn you before you press YES.

## herdr and the usagebar plugin

herdr is optional. With it, SHOW ME brings the item's pane forward, Home shows a herdr line, and the context gauge works. The bridge runs only `herdr agent list` and `herdr agent focus`.

herdr does not count tokens itself. The context gauge reads `tokens.context`, which the usagebar plugin for herdr ([senna-lang/herdr-agent-usage](https://github.com/senna-lang/herdr-agent-usage)) writes for each agent. Install it from its README. Without it the gauge reads unknown.

## quota-axi and the Keychain step

The usage gauge comes from `quota-axi --provider claude --json --no-credential-refresh`, run every 5 minutes. The bridge never renews a session itself, so on macOS quota-axi can read Claude's credentials from the Keychain only after you allow it once, by hand:

```sh
quota-axi --allow-keychain-prompt
```

Choose "Always Allow" when macOS asks. Until then the bridge logs `claude quota auth_required (keychain_prompt_required)` and the gauge reads unknown, never full.

## lavish-axi

SHOW ME opens an item's live Lavish review board, or renders its report as a page and opens it with `lavish-axi`. Without `lavish-axi` on `PATH`, SHOW ME opens the item's PR when it has one, and otherwise only focuses its pane.

## The doctor

`python3 -m helm.bridge --doctor` checks, in order:

| Check | `missing` when | `warn` when |
| --- | --- | --- |
| `home` | the path is not a directory, or has no `state/` or no executable `bin/fm-inbox.sh` | never |
| `ready` | `fm-inbox.sh ready` fails or prints another schema | `can_receive` is not true |
| `YES rule` | never | the YES opening words are not in `data/captain.md` (or the primary's `data/captain-shared.md`), or the rule there never mentions `--expected-head` |
| `summary <home>` | the primary's summary is absent, unreadable, or another schema | a second mate's is, or a summary says `valid: false` |
| `fleet ledger <home>` | never | the flag is off, or the ledger is over 50 MB |
| `pr health <home>` | never | the flag is off |
| `herdr` | never | herdr is not on `PATH`, or `herdr agent list` fails |
| `context tokens` | never | no running agent reports a context percent |
| `quota-axi` | never | it is not on `PATH`, or its reading is not fresh (the Keychain step names its own fix) |
| `lavish-axi` | never | it is not on `PATH` |

The per-home checks run for the primary and every second mate home its `data/secondmates.md` lists. The doctor runs `fm-inbox.sh ready`, `herdr agent list`, and the usage gauge's `quota-axi` read through the bridge's allowlist with writes refused; it never runs `lavish-axi`, and it never creates or changes a file.

Example, for a home with the rule and flags in place but no Keychain step yet:

```text
helm doctor, read only: /path/to/firstmate
ok      home: /path/to/firstmate has bin/fm-inbox.sh and state/
ok      ready: fm-primary-ready.v1, can_receive true, posture present
ok      YES rule: found in data/captain.md, with the commit pin
ok      summary primary: fm-secondmate-home-summary.v1, valid, published 2m ago
ok      fleet ledger primary: on, state/fleet-ledger.jsonl is 682.4 KB
ok      pr health primary: on
ok      herdr: reachable, 6 agent(s)
ok      context tokens: 5 of 6 agent(s) report tokens.context
warn    quota-axi: claude quota auth_required (keychain_prompt_required) Fix: run `quota-axi --allow-keychain-prompt` once by hand and choose Always Allow.
ok      lavish-axi: on PATH
9 ok, 1 warn, 0 missing. Setup guide: docs/firstmate-setup.md
```
