#!/usr/bin/env bash
# Show or move the pinned upstream revisions.
#   ./scripts/update-upstream.sh                    # status: pinned vs. latest remote commit
#   ./scripts/update-upstream.sh lyrebird [REF]     # move one submodule to REF (default: origin HEAD)
# e.g. try Lyrebird's onboard-mission fixes:  ./scripts/update-upstream.sh lyrebird onboard_mission_fixes
# Then rebuild (docker compose build) and commit the new pin (git add upstream/<name>).
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -eq 0 ]]; then
  git submodule foreach --quiet '
    pinned=$(git rev-parse --short HEAD)
    remote=$(git ls-remote origin HEAD | cut -c1-7)
    printf "%-38s pinned %s  remote HEAD %s %s\n" "$sm_path" "$pinned" "$remote" "$([ "$pinned" = "$remote" ] && echo "(aktuell)")"'
  exit 0
fi
path="upstream/$1"; ref="${2:-HEAD}"
[[ -d "$path" ]] || { echo "unbekannt: $path" >&2; exit 1; }
git -C "$path" fetch --depth 50 origin "$ref"
git -C "$path" checkout --detach FETCH_HEAD
echo "$path -> $(git -C "$path" rev-parse --short HEAD). Commit mit: git add $path && git commit"
