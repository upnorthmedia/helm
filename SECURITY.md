# Security

## Reporting a problem

Please report a security problem privately through GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability** (https://github.com/upnorthmedia/helm/security/advisories/new). If that form is not available, open an issue that says only that you have a security report and asks for a private channel. Do not put details in a public issue.

Helm has no releases yet. Reports are handled against `main`.

## Threat model

Helm is a desk device and a small program on your Mac, the bridge, that sits between the device and firstmate. This section says what the bridge trusts, what it guards, and what it does not try to defend against.

### What Helm can do on your Mac

The bridge runs as you, from a launchd user agent. It runs external commands only through one allowlist in [`helm/bridge/commands.py`](helm/bridge/commands.py), which is the source of truth; anything not on it is refused before a process starts. Today the list is:

- Reads: `fm-inbox.sh ready` and `receipts`, `herdr agent list`, `quota-axi --provider claude --json`, `ioreg -n Root -d1 -a`, and `lavish-axi` alone (list the open review boards).
- Writes: `fm-inbox.sh note` and `announce` (a note to your primary firstmate home), `herdr agent focus` (bring a pane forward), `lavish-axi <page>` for a page in the bridge's cache or a firstmate home's `data/` directory, and `open <url>` for a review board on this Mac or a GitHub pull request.

The bridge never merges, pushes, types into a pane, or starts, stops, or tears down anything in firstmate. Firstmate's merge, send, control, wake, and teardown scripts are not on the allowlist.

### Dry run by default

The bridge starts in dry run: notes, focus, and opens are logged, not run. Write commands run only when you start it with `--live`, and the allowlist refuses them otherwise, on top of the dry-run switch in the code that turns key presses into notes. Rerunning `scripts/install-agent.sh` without `--live` puts an installed agent back into dry run.

### What a key press becomes

A held YES, LATER, or HOLD becomes exactly one `fm-inbox.sh note` in your primary firstmate home. The bridge acts only on the item the deck named in the key event, refuses a key for an item that is gone, keeps YES dark on a pull request known to be red or conflicted, and refuses every key while the Mac is locked, reading the lock again right before it acts. A YES on a pull request names the commit the deck showed, so with the YES rule firstmate can refuse the merge if anything was pushed since.

Firstmate does the acting. By default firstmate does not treat a note from a bridge as approval of anything. A YES becomes your word only if you add a rule to your own firstmate home that tells firstmate to treat a note starting with the deck's exact YES wording as your word for the one pull request or decision it names (see [The YES rule](README.md#the-yes-rule)).

### Same-user trust

Helm does not defend against software running as you. Any process running as your user can do what the bridge can: write the same note to firstmate's inbox with the same wording, write key events to the deck's serial port, or edit the launchd agent. The one second hold is enforced on the deck, not in the bridge, so a key event that arrives on the serial port is trusted as a held press. Firstmate's own local records prove consistency, not who wrote them. If untrusted code runs as your user, Helm is not the boundary that stops it.

### What a forged note can and cannot do

Without the YES rule, a forged YES note is a message to firstmate and approves nothing.

With the YES rule, someone who can run code as you can forge a YES note. Within firstmate's own guards, the most it can do is:

- get firstmate to merge one pull request that a task in that home owns, through firstmate's own merge command, which reads the pull request live and refuses unless it is open, not a draft, mergeable, conflict free, and green at its current commit; or
- get firstmate to go with its own recommendation on one open decision, when it gave exactly one.

A forged LATER or HOLD note can defer an item or pause work on it until you notice.

A forged note cannot push code, merge a pull request that is red, a draft, or conflicted, act on work outside that firstmate home, or run commands on the bridge's behalf. Those limits come from firstmate's guards and the allowlist above, not from the note's wording.

### What the deck sees

The deck receives the full text of every item it shows, over USB. Anyone who can read the serial port, which again means software running as you, can read it. Helm has no wireless link.

### CI and pull requests

Pull requests from people other than the repository owner must be raised through [no-mistakes](https://github.com/kunchenguid/no-mistakes); a required check reads the pipeline attestation no-mistakes writes into the pull request body and checks that it names the current head commit with the review, test, and document steps completed. That check is structural, a guardrail for honest contributors and not a cryptographic proof: an author can edit their own pull request body, so review is still the boundary. Workflow actions are pinned by commit, and a hygiene check fails a pull request that adds a home directory path, a personal email address, or a known token format. See [CONTRIBUTING.md](CONTRIBUTING.md).
