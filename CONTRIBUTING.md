# Contributing

Thanks for wanting to help with Helm. One rule up front:

**Pull requests to `main` must be raised through [no-mistakes](https://github.com/kunchenguid/no-mistakes)**, unless you are the repository owner.

no-mistakes puts a local git proxy in front of your real remote. Pushing through it runs a review, test, and lint pipeline in an isolated worktree, pushes your branch only after every step passes, and opens the pull request for you. The required check `PR must be raised via no-mistakes` (workflow `Require no-mistakes`) fails a pull request whose body lacks the signature and the pipeline attestation that no-mistakes writes, or whose attestation does not match the pull request's current head commit. It runs again when the pull request is opened, edited, pushed to, or reopened. The repository owner and GitHub's automation accounts are exempt; the owner ships directly.

If you edit the pull request description after no-mistakes opens it, keep its `## Pipeline` section. Removing it fails the check until you push through no-mistakes again.

## Workflow

You need no-mistakes v1.46.0 or newer; older versions do not write the attestation the check reads.

1. Fork the repository, then clone the parent repository, or set your local `origin` back to it (`git@github.com:upnorthmedia/helm.git`).
2. Create a branch and make your changes.
3. Set up the gate with your fork as the push target: `no-mistakes init --fork-url git@github.com:<you>/helm.git`.
4. Commit your changes.
5. Push through the gate instead of to `origin`:

   ```sh
   git push no-mistakes
   ```

6. Run `no-mistakes` to attach to the pipeline, watch its findings, and approve fixes or answer its questions.
7. When the pipeline passes, it pushes the branch to your fork and opens the pull request against this repository.

The [no-mistakes quick start](https://kunchenguid.github.io/no-mistakes/start-here/quick-start/) walks through a first run.

## Checks to run first

The pipeline and CI run these again, but a local pass saves rounds. Run them from the repository root.

```sh
python3 -m unittest discover -s tests -t .   # bridge, simulator, wire, scripts
scripts/test-firmware.sh                      # firmware core: C tests under ASan and UBSan, then cross-tests
scripts/check-hygiene.sh                      # public repository hygiene (below)
```

CI also runs `ruff check`, `shellcheck` on every `*.sh`, `actionlint`, and `reuse lint`, with the versions pinned in [`.github/workflows/tests.yml`](.github/workflows/tests.yml), and the Python suite and scripts on macOS with its stock bash 3.2. Scripts in `scripts/` must run on that bash: no `mapfile`, no associative arrays.

If you change `case/`, set up the case environment ([case/README.md](case/README.md)), run its tests, and rebuild:

```sh
case/.venv/bin/python -m unittest discover -s case/tests
case/.venv/bin/python case/build.py
```

Commit the rebuilt `case/out/`. CI rebuilds the case when `case/` changes and fails if `case/out/checks.txt` differs from the committed one.

The ESP-IDF firmware (`firmware/idf/`) builds in CI in Espressif's image; see [firmware/idf/README.md](firmware/idf/README.md) to build it locally.

## Rules for changes

- **The bridge stays standard library only.** `helm/` runs on a stock Python 3.11 or newer with nothing installed. Lint tools are CI only.
- **The wire stays compatible.** A deck flashed months ago must keep working with a new bridge, and the reverse. New fields are optional, have defaults, and older decoders ignore them; the frame format does not change in a way an older deck cannot read; the 8192 byte frame must still fit.
- **The allowlist is the boundary.** The bridge runs external commands only through [`helm/bridge/commands.py`](helm/bridge/commands.py). It never merges, pushes, types into a pane, or touches firstmate's lifecycle. A change that adds a command there needs a reason in the pull request and a test. See [SECURITY.md](SECURITY.md).
- **Tests come with behavior.** A behavior change comes with a test; a bug fix comes with a test that fails without the fix.

## Pull request titles and merging

Use a [Conventional Commits](https://www.conventionalcommits.org/) title: `fix(bridge): ...`, `feat(sim): ...`, `docs: ...`, `test: ...`, `ci: ...`, `chore: ...`. Pull requests are squash merged, so the title becomes the commit on `main`. A pull request must be up to date with `main` and green on every required check before it merges.

## Public repository hygiene

Everything here is public, including commit messages and pull request text. Do not commit:

- paths from your own machine, such as your home directory;
- a personal email address (use your GitHub noreply address for commits);
- names of private projects, people, or internal tools, or notes and state copied from your own agent setup;
- credentials, tokens, or keys.

`scripts/check-hygiene.sh` checks every tracked file for home directory paths, email addresses other than the repository's noreply author, and the patterns in [`.github/hygiene-deny.txt`](.github/hygiene-deny.txt). Names you cannot publish even as a pattern go in a private list outside the repository: `scripts/check-hygiene.sh --deny <file>`.

## Licensing

Helm uses several licenses, mapped path by path in [`REUSE.toml`](REUSE.toml): Apache-2.0 for software, CERN-OHL-W-2.0 for the case design (`case/`) and build guides (`docs/build/`), and CC BY 4.0 for other documentation and images. The Helm logo is not under an open license. By submitting a contribution, you agree that it is licensed under the license `REUSE.toml` gives its path. If you add a file that should be under a different license, or third-party material, update `REUSE.toml` and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md); CI runs `reuse lint`.

## Issues

Use the issue forms for a bug, a question about building one, or a report from a real board (Helm has not run on one yet, so these are especially welcome). Report security problems privately, as [SECURITY.md](SECURITY.md) describes. Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
