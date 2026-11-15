#!/usr/bin/env bash
# Run the firstmate contract tests (tests/test_firstmate_contract.py) against a
# real firstmate checkout: the pinned commit below, or any ref of firstmate.
#
#   scripts/test-firstmate-contract.sh          # the pinned commit, as CI does on every pull request
#   scripts/test-firstmate-contract.sh main     # firstmate's main, as the weekly drift run does
#   HELM_FIRSTMATE=<checkout> scripts/test-firstmate-contract.sh   # an existing checkout, as it stands
#
# Fetches github.com/kunchenguid/firstmate read-only into a temporary
# directory and deletes it afterwards. The tests run firstmate's scripts in a
# temporary home of their own, never in a real one. Needs git, bash, jq, and
# Python 3.11 or newer (set PYTHON to pick one). Prints the firstmate commit it
# tested, and writes it as `commit=<sha>` to $GITHUB_OUTPUT when that is set.
set -euo pipefail

# The firstmate commit Helm is tested against. Bump it in a pull request of its
# own, once these tests pass against the new commit.
FIRSTMATE_PIN=427056c4181c41074ad24f051f79919330df0fa5
FIRSTMATE_REPO=https://github.com/kunchenguid/firstmate.git
PYTHON=${PYTHON:-python3}

die() { echo "test-firstmate-contract: $*" >&2; exit 2; }

[ $# -le 1 ] || die "usage: scripts/test-firstmate-contract.sh [<firstmate ref>]"
root="$(cd "$(dirname "$0")/.." && pwd)"

if [ -n "${HELM_FIRSTMATE:-}" ]; then
  [ $# -eq 0 ] || die "HELM_FIRSTMATE names a checkout already; drop the ref"
  checkout="$HELM_FIRSTMATE"
else
  ref="${1:-$FIRSTMATE_PIN}"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  checkout="$tmp/firstmate"
  git init -q "$checkout"
  git -C "$checkout" fetch -q --depth 1 "$FIRSTMATE_REPO" "$ref"
  git -C "$checkout" -c advice.detachedHead=false checkout -q FETCH_HEAD
fi

commit="$(git -C "$checkout" rev-parse HEAD)"
echo "firstmate commit: $commit (pinned: $FIRSTMATE_PIN)"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "commit=$commit" >> "$GITHUB_OUTPUT"
fi

cd "$root"
HELM_FIRSTMATE="$checkout" "$PYTHON" -m unittest -v tests.test_firstmate_contract
