#!/usr/bin/env bash
# retry.sh CMD...   Run CMD once per RETRY_DELAYS entry (default "10 30 60 120 240" -> 5 attempts).
#   The entries are the back-off between attempts, so only the first N-1 are slept: with the
#   default, 4 sleeps of 10+30+60+120 = 220 s worst case; the last entry (240) caps attempts and
#   is never slept (300 s if a rate-limit floor raises an early delay).
# Classification of the combined stdout+stderr of a failed attempt, in this order:
#   1. transient-first -> retry   (rate limits incl. GitHub 403s, registry DB errors behind a 400, 5xx, network)
#   2. permanent       -> stop    (auth, 404/422, validation, immutability, duplicates)   exit 1
#   3. anything else   -> retry
# Exit: 0 ok; 1 permanent; 2 attempts exhausted; 130/143 on INT/TERM.
# `scripts/ci/retry.sh --self-test` runs the fixtures at the bottom (lint.yml).
set -uo pipefail

TRANSIENT='rate limit|retry-after|abuse detection|failed to begin transaction|connection refused|connection reset|dial tcp|timed? ?out|deadline exceeded|TLS handshake|unexpected EOF|Could not resolve host|(status|HTTP) (5[0-9][0-9]|429|408)'
PERMANENT="(status|HTTP) (401|403|404|422)|Bad credentials|Resource not accessible|does not have 'workflow_dispatch'|already exists|duplicate version|Cannot (delete|upload|modify) asset|immutable|invalid audience|not verified|status 400:.*(validation|schema|invalid|ownership|mcp-name|not authori[sz]ed|permission)"
RATELIMIT='rate limit|retry-after|abuse detection'

retry() {
  # Only the successful attempt's stdout reaches our stdout, so `x=$(retry cmd ... --jq .id)`
  # captures the command's output alone, never a failed attempt's error text or our notices.
  # Failed-attempt output and all notices go to stderr; classification still reads both streams.
  local delays attempt=1 out err body rc d
  read -ra delays <<<"${RETRY_DELAYS:-10 30 60 120 240}"
  ef=$(mktemp)
  while :; do
    out=$("$@" 2>"$ef"); rc=$?; err=$(cat "$ef")
    if [ "$rc" -eq 0 ]; then
      printf '%s\n' "$out"                                   # clean stdout: the command's output only
      [ -z "$err" ] || printf '%s\n' "$err" >&2             # keep its stderr visible in the log
      rm -f "$ef"; return 0
    fi
    body="$out"$'\n'"$err"                                   # classify over both streams, as before
    { [ -z "$out" ] || printf '%s\n' "$out"; [ -z "$err" ] || printf '%s\n' "$err"; } >&2
    if ! grep -Eiq "$TRANSIENT" <<<"$body" && grep -Eiq "$PERMANENT" <<<"$body"; then
      echo "::error::permanent error on attempt $attempt of '$1' (rc=$rc)" >&2; rm -f "$ef"; return 1
    fi
    [ "$attempt" -ge "${#delays[@]}" ] && { echo "::error::giving up on '$1' after $attempt attempts" >&2; rm -f "$ef"; return 2; }
    d=${delays[$((attempt - 1))]}
    if grep -Eiq "$RATELIMIT" <<<"$body"; then
      d=$(( d > ${RETRY_RATELIMIT_MIN:-60} ? d : ${RETRY_RATELIMIT_MIN:-60} ))   # secondary limits: wait at least a minute
    fi
    echo "::notice::attempt $attempt of '$1' failed (rc=$rc); retrying in ${d}s" >&2
    sleep "$d"; attempt=$((attempt + 1))
  done
}

self_test() {
  export RETRY_DELAYS="0 0 0 0 0" RETRY_RATELIMIT_MIN=0
  local counter; counter=$(mktemp)
  flaky() {  # $1 message, $2 failures before success; counts attempts in $counter (survives subshells)
    local c; c=$(cat "$counter"); echo $((c + 1)) > "$counter"
    [ "$c" -ge "$2" ] && return 0
    echo "$1"; return 1
  }
  check() {  # name want_rc want_attempts message failures
    echo 0 > "$counter"; retry flaky "$4" "$5" > /dev/null 2>&1; local rc=$?
    if [ "$rc" = "$2" ] && [ "$(cat "$counter")" = "$3" ]; then echo "ok   $1"; else
      echo "FAIL $1: rc=$rc attempts=$(cat "$counter") (want rc=$2 attempts=$3)"; rm -f "$counter"; exit 1; fi
  }
  noisy() {  # fails $2 times printing noise to both streams, then succeeds printing "12345" to stdout
    local c; c=$(cat "$counter"); echo $((c + 1)) > "$counter"
    if [ "$c" -ge "$2" ]; then echo 12345; return 0; fi
    echo "$1"; echo "noise on stderr" >&2; return 1
  }
  check transient-then-ok       0 3 "publish failed: server returned status 503: upstream" 2
  check permanent-401           1 1 "HTTP 401: Bad credentials" 9
  check exhausted               2 5 "dial tcp 1.2.3.4:443: connect: connection refused" 9
  check ratelimit-403-retries   0 2 "HTTP 403: You have exceeded a secondary rate limit" 1
  check forbidden-403-stops     1 1 "HTTP 403: Resource not accessible by integration" 9
  check registry-db-400-retries 0 2 'publish failed: server returned status 400: {"detail":"Failed to publish server","errors":[{"message":"failed to begin transaction: dial tcp: connect: connection refused"}]}' 1
  check registry-validation-400 1 1 'publish failed: server returned status 400: {"detail":"Failed to publish server","errors":[{"message":"validation failed: packages[0].identifier"}]}' 9
  check duplicate-stops         1 1 'publish failed: server returned status 400: {"errors":[{"message":"io.github.x/y@1.0.0 already exists"}]}' 9
  check dispatch-422-stops      1 1 "HTTP 422: Workflow does not have 'workflow_dispatch' trigger" 9
  check unknown-retries         0 2 "something odd happened" 1
  # a failed attempt's noise must not leak into captured stdout: one transient failure then success
  local got; echo 0 > "$counter"; got=$(retry noisy "dial tcp: connection refused" 1 2>/dev/null)
  if [ "$got" = "12345" ]; then echo "ok   clean-stdout"; else
    echo "FAIL clean-stdout: got '$got' want '12345'"; rm -f "$counter"; exit 1; fi
  rm -f "$counter"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  trap 'rm -f "${ef:-}"; echo "interrupted" >&2; exit 130' INT
  trap 'rm -f "${ef:-}"; exit 143' TERM
  if [ "${1:-}" = --self-test ]; then self_test; exit 0; fi
  [ $# -gt 0 ] || { echo "usage: retry.sh CMD... | --self-test" >&2; exit 64; }
  retry "$@"
fi
