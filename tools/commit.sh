#!/usr/bin/env bash
# Guarded atomic commit. Usage: tools/commit.sh "message" path [path...]
# - Hard cap: at most 43 commits dated today in this repo. At/over the cap it
#   stages NOTHING and exits 0 (changes are left unstaged, by request).
# - Commits ONLY the listed paths (git commit --only), so parallel agents never
#   sweep up each other's staged work.
# - Serialized with a mkdir mutex so concurrent agents can't race the counter.
set -euo pipefail
CAP=43
cd "$(git rev-parse --show-toplevel)"
[ $# -ge 2 ] || { echo "usage: tools/commit.sh \"message\" path [path...]" >&2; exit 2; }
msg="$1"; shift
lock=".git/commit-guard.lock"
for _ in $(seq 1 300); do mkdir "$lock" 2>/dev/null && break; sleep 0.2; done
[ -d "$lock" ] || { echo "could not acquire $lock" >&2; exit 1; }
trap 'rmdir "$lock" 2>/dev/null || true' EXIT
today=$(date +%Y-%m-%d)
count=0
if git rev-parse -q --verify HEAD >/dev/null; then
  count=$(git log --all --since="$today 00:00" --format=%H | sort -u | wc -l | tr -d ' ')
fi
if [ "$count" -ge "$CAP" ]; then
  echo "COMMIT CAP REACHED ($count/$CAP today): leaving changes UNSTAGED. Not committing: $msg"
  exit 0
fi
git add -- "$@"
if git diff --cached --quiet -- "$@"; then
  echo "nothing to commit for: $*"; exit 0
fi
git commit -q --only -m "$msg" -- "$@"
echo "committed $(git rev-parse --short HEAD) [$((count+1))/$CAP today]: $msg"
