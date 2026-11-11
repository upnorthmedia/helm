#!/usr/bin/env bash
# Check that no tracked file carries something that must stay out of a public
# repository: a home directory path, an email address other than the repo's
# own noreply author, or a line matching a pattern in a deny list.
#
#   scripts/check-hygiene.sh [--deny FILE]...
#
# Scans every file git tracks in the repository that holds the current
# directory, skipping binary files. The committed deny list,
# .github/hygiene-deny.txt, is always read when present; each --deny adds
# another list, such as a private one kept outside the repository for names
# that cannot be published even as a pattern. A deny list holds one extended
# regular expression per line; blank lines and lines starting with # are
# ignored. Prints each hit as path:line: reason and exits 1 if there are any.
set -euo pipefail

ALLOWED_EMAILS="118795184+upnorthmedia@users.noreply.github.com git@github.com"
DEFAULT_DENY=".github/hygiene-deny.txt"

die() { echo "check-hygiene: $*" >&2; exit 2; }

deny_files=()
while [ $# -gt 0 ]; do
  case "$1" in
    --deny)
      [ $# -ge 2 ] || die "--deny needs a file"
      [ -f "$2" ] || die "no such deny list: $2"
      deny_files+=("$2")
      shift 2
      ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

root="$(git rev-parse --show-toplevel)" || die "not inside a git repository"
cd "$root"
[ -f "$DEFAULT_DENY" ] && deny_files=("$DEFAULT_DENY" ${deny_files[@]+"${deny_files[@]}"})

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# The deny list itself is made of the patterns it forbids, so it is not scanned.
git ls-files -z -- . ":(exclude)$DEFAULT_DENY" > "$tmp/files"

scan() {  # scan PATTERN: print path:line:text for each match
  xargs -0 grep -I -n -H -E -e "$1" /dev/null < "$tmp/files" || true
}

hits=0
report() {  # report REASON, reading path:line:text lines on stdin
  while IFS= read -r line; do
    echo "${line%%:*}:$(echo "$line" | cut -d: -f2): $1"
    hits=$((hits + 1))
  done
}

report "home directory path" < <(scan '/(Users|home)/[^/[:space:]]')

xargs -0 grep -I -n -H -o -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' /dev/null \
  < "$tmp/files" > "$tmp/emails" || true
while IFS= read -r line; do
  addr="${line##*:}"
  case " $ALLOWED_EMAILS " in
    *" $addr "*) ;;
    *) echo "${line%:*}: email address $addr"; hits=$((hits + 1)) ;;
  esac
done < "$tmp/emails"

for list in ${deny_files[@]+"${deny_files[@]}"}; do
  grep -v -E '^[[:space:]]*(#|$)' "$list" > "$tmp/patterns" || true
  while IFS= read -r pattern; do
    report "matches deny pattern in $list" < <(scan "$pattern")
  done < "$tmp/patterns"
done

if [ "$hits" -gt 0 ]; then
  echo "check-hygiene: $hits problem(s); see CONTRIBUTING.md (public repository hygiene)" >&2
  exit 1
fi
echo "check-hygiene: $(tr -cd '\0' < "$tmp/files" | wc -c | tr -d ' ') tracked files clean"
