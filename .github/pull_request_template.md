<!--
The repository owner's pull requests use this template. Everyone else raises
pull requests through no-mistakes, which writes the body; keep its Pipeline
section. See CONTRIBUTING.md.

Title: a Conventional Commits title, such as "fix(bridge): ...". It becomes
the squash commit on main.
-->

## What and why

<!-- What changes, and the problem it solves. Link an issue if there is one. -->

## Testing

<!-- The commands you ran and what they showed. Say what was not tested. -->

- [ ] `python3 -m unittest discover -s tests -t .`
- [ ] `scripts/test-firmware.sh` (if `firmware/core` or `helm/wire` changed)
- [ ] case tests and `case/build.py`, with `case/out/` committed (if `case/` changed)
- [ ] `scripts/check-hygiene.sh`

## Compatibility

- [ ] New wire fields are optional, and an older deck still reads every frame (or the wire is unchanged)
- [ ] No new command on the bridge's allowlist (or the reason is above)
