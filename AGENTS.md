# Notes for agents working on Helm

Helm is a desk device for firstmate: an ESP32-P4 deck (`firmware/`), a deck simulator (`sim/`), the wire between them (`helm/wire/`, `helm/contract.py`), the bridge on the Mac (`helm/bridge/`), and a sheet-metal case (`case/`). [CONTRIBUTING.md](CONTRIBUTING.md) has the full contributor rules.

## Test commands

Run from the repository root:

```sh
python3 -m unittest discover -s tests -t .   # the whole Python suite; keep it green
scripts/test-firmware.sh                      # firmware core C tests and cross-tests (needs cmake)
scripts/check-hygiene.sh                      # public repository hygiene
```

Case changes also need `case/.venv/bin/python -m unittest discover -s case/tests` and `case/.venv/bin/python case/build.py`, with the rebuilt `case/out/` committed (setup in `case/README.md`). CI adds `ruff check`, `shellcheck`, `actionlint`, `reuse lint`, and the suite on macOS with stock bash 3.2.

## Public repository hygiene

This repository is public. Commits, pull request text, code, comments, fixtures, and docs carry no personal email address (commit with the repository's noreply author), no home directory paths, no private notes or state from any firstmate home, no names of private projects, and no AI attribution. `scripts/check-hygiene.sh` enforces the mechanical part.

## Never-call list

The bridge never merges, never pushes, never types into a pane, and never starts, stops, or tears down anything in firstmate (no `fm-pr-merge.sh`, `fm-send.sh`, `fm-control.sh`, `fm-wake-drain.sh`, `fm-inbox.sh drain`, `fm-teardown.sh`, `fm-home-summary-refresh.sh`, or `tasks-axi`). The allowlist in `helm/bridge/commands.py` is the source of truth: anything not on it is refused before a process starts. Do not widen it without a stated reason and a test. The bridge stays standard library only.

## Wire compatibility

Old decks and new bridges must keep working together, and the reverse. New fields are optional with defaults, and old decks ignore them. Never change the frame format in a way an older deck cannot read, and keep a full model inside the 8192 byte frame.
