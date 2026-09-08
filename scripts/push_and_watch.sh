#!/usr/bin/env bash
# One-shot: create the private GitHub repo, push, and stream the first CI run.
#
# Prerequisite: `gh auth status` succeeds (run `gh auth login --web --scopes
# repo,workflow` first). This script does nothing else that needs a human.
#
#   bash scripts/push_and_watch.sh [repo-name]
#
# Default repo name: sentinelmesh. Visibility: private.

set -euo pipefail

REPO_NAME="${1:-sentinelmesh}"
GH="${GH:-gh}"

if ! "$GH" auth status >/dev/null 2>&1; then
  echo "error: not authenticated. Run:  $GH auth login --web --scopes repo,workflow" >&2
  exit 1
fi

cd "$(git rev-parse --show-toplevel)"

if git remote get-url origin >/dev/null 2>&1; then
  echo "origin already set: $(git remote get-url origin)"
  git push -u origin HEAD
else
  "$GH" repo create "$REPO_NAME" \
    --private \
    --source=. \
    --remote=origin \
    --push \
    --description "AI-native cybersecurity threat detection and attack-intelligence platform (Phase 1)"
fi

echo
echo "watching the CI run triggered by the push..."
sleep 5
RUN_ID="$("$GH" run list --limit 1 --json databaseId --jq '.[0].databaseId')"
"$GH" run watch "$RUN_ID" --exit-status || true

echo
echo "=== job results ==="
"$GH" run view "$RUN_ID" --json jobs \
  --jq '.jobs[] | "\(.name): \(.conclusion // .status)"'
echo
echo "full log:  $GH run view $RUN_ID --log"
