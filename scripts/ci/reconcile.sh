#!/usr/bin/env bash
# Complete any of the last 3 release tags whose PyPI / GitHub release / registry state is not done.
# Runs every 6 h, once after a failed Publish run (+5 min), and by hand. Bounded: 8 failed runs per tag.
set -euo pipefail
trap 'exit 130' INT
trap 'exit 143' TERM
cd "$(dirname "$0")/../.."
N=3; CAP=8; R=$GITHUB_REPOSITORY; rc=0
summary() { echo "$1" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"; }

if [ "${RUN_EVENT:-}" = workflow_run ]; then
  case "${RUN_CONCLUSION:-}" in failure|timed_out) ;; *) echo "publish run concluded '${RUN_CONCLUSION:-}'; nothing to do"; exit 0 ;; esac
  sleep 300   # let a PyPI / registry blip pass before retrying
fi

summary "| tag | state | action |"; summary "|---|---|---|"
for t in $(gh api --paginate --slurp "repos/$R/tags?per_page=100" | jq -r 'add // [] | .[].name' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -rV | head -n "$N"); do
  env -u GITHUB_STEP_SUMMARY -u GITHUB_OUTPUT scripts/ci/state.sh all "$t" > /tmp/state.txt 2>&1 && srv=0 || srv=$?
  state=$(tr '\n' ' ' < /tmp/state.txt)
  if [ "$srv" -eq 0 ]; then act="done"
  elif [ "$srv" -eq 2 ]; then act="unfixable, needs a human"
  else
    if ! runs=$(gh api "repos/$R/actions/workflows/publish.yml/runs?branch=$t&per_page=100" --jq '.workflow_runs') \
       || ! gh api "repos/$R/contents/pyproject.toml?ref=$t" --jq .content | base64 -d > /tmp/pyproject.toml; then
      act="could not read runs/pyproject (GitHub API)"; rc=1
      echo "$t: $state-> $act"; summary "| $t | $state | $act |"; continue
    fi
    active=$(jq '[.[]|select(.status=="queued" or .status=="in_progress" or .status=="waiting" or .status=="pending" or .status=="requested")]|length' <<<"$runs")
    failed=$(jq '[.[]|select((.conclusion=="failure" or .conclusion=="timed_out") and ((.display_title|test("\\[fail_at\\]"))|not))]|length' <<<"$runs")
    tagv=$(python3 -c 'import tomllib;print(tomllib.load(open("/tmp/pyproject.toml","rb"))["project"]["version"])')
    if   [ "$tagv" != "${t#v}" ]; then act="invalid: pyproject at the tag says $tagv; needs a human"
    elif [ "$active" -gt 0 ]; then act="publish run in progress"
    elif [ "$failed" -ge "$CAP" ]; then act="$failed failed runs (cap $CAP); needs a human"
    elif [ "${RUN_EVENT:-}" = workflow_run ] && [ "$failed" -gt 2 ]; then act="left to the 6-hourly schedule ($failed failures so far)"   # push + release dispatch = 2 runs per release
    elif dispatch=$(scripts/ci/retry.sh gh workflow run publish.yml --ref "refs/tags/$t" 2>&1); then act=dispatched
    elif grep -q "workflow_dispatch" <<<"$dispatch"; then act="pre-rollout tag; cannot dispatch"
    else act="dispatch failed: $(tail -n 1 <<<"$dispatch")"; rc=1
    fi
  fi
  echo "$t: $state-> $act"; summary "| $t | $state | $act |"
done
exit $rc
