#!/usr/bin/env bash
# Turn on the protections GitHub only offers for public repos (on the Free plan).
# Run right after making the repo public:   scripts/protect_main.sh jigstore/jigstore
#
#  1. the main-branch ruleset in .github/rulesets/main.json
#  2. maintainer approval before CI runs on a first-time contributor's pull request
#  3. private vulnerability reporting (the link in SECURITY.md)
set -euo pipefail
repo="${1:-jigstore/jigstore}"
here="$(cd "$(dirname "$0")/.." && pwd)"

existing="$(gh api "repos/$repo/rulesets" --jq '.[] | select(.name=="Protect main") | .id')"
if [ -n "$existing" ]; then
  gh api -X PUT "repos/$repo/rulesets/$existing" --input "$here/.github/rulesets/main.json" --jq '"updated ruleset \(.id)"'
else
  gh api -X POST "repos/$repo/rulesets" --input "$here/.github/rulesets/main.json" --jq '"created ruleset \(.id)"'
fi

gh api -X PUT "repos/$repo/actions/permissions/fork-pr-contributor-approval" -f approval_policy=first_time_contributors
echo "first-time contributors need approval before CI runs"

gh api -X PUT "repos/$repo/private-vulnerability-reporting"
echo "private vulnerability reporting enabled"
