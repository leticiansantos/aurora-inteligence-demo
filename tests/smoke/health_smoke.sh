#!/usr/bin/env bash
# Smoke test for a deployed Databricks App: calls GET /api/health with the
# caller's user OAuth token (from the CLI profile) and asserts that the app
# answered from a live Unity Catalog query run as the app service principal.
#
# Usage: tests/smoke/health_smoke.sh <profile> <app-name> [--schema CATALOG.SCHEMA] [--out FILE]
#   Callable from deploy.sh:  "$REPO_ROOT/tests/smoke/health_smoke.sh" "$PROFILE" "$APP_NAME"
# Exit code: 0 = healthy, 1 = assertion failed, 2 = usage / tooling error.
# The token is never printed or written to --out.
set -uo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <profile> <app-name> [--out FILE]" >&2; exit 2
fi
PROFILE="$1"; APP_NAME="$2"; shift 2
OUT=""
EXPECTED_SCHEMA="${EXPECTED_SCHEMA:-classic_stable.auto_intelligence}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --schema) EXPECTED_SCHEMA="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
RETRIES="${RETRIES:-10}"        # app may still be starting right after deploy
RETRY_DELAY="${RETRY_DELAY:-15}"

for bin in databricks jq curl; do
  command -v "$bin" >/dev/null || { echo "missing tool: $bin" >&2; exit 2; }
done

log() { echo "$*"; [[ -n "$OUT" ]] && echo "$*" >> "$OUT"; return 0; }
[[ -n "$OUT" ]] && : > "$OUT"

app_json=$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json) \
  || { echo "cannot read app $APP_NAME" >&2; exit 2; }
url=$(jq -r '.url // empty' <<<"$app_json")
sp_app_id=$(jq -r '.service_principal_client_id // empty' <<<"$app_json")
log "app:            $APP_NAME"
log "url:            $url"
log "app_state:      $(jq -r '.app_status.state // "?"' <<<"$app_json")"
log "compute_state:  $(jq -r '.compute_status.state // "?"' <<<"$app_json")"
log "sp_client_id:   $sp_app_id"
[[ -n "$url" ]] || { log "FAIL: app has no URL"; exit 1; }

token=$(databricks auth token --profile "$PROFILE" | jq -r '.access_token // empty')
[[ -n "$token" ]] || { echo "cannot get an OAuth token for profile $PROFILE" >&2; exit 2; }

body=""; code=""
for ((i = 1; i <= RETRIES; i++)); do
  resp=$(curl -sS -m 60 -w '\n%{http_code}' -H "Authorization: Bearer $token" "$url/api/health") || resp=$'\n000'
  code=$(tail -n1 <<<"$resp"); body=$(sed '$d' <<<"$resp")
  [[ "$code" == "200" ]] && break
  log "attempt $i/$RETRIES: HTTP $code, retrying in ${RETRY_DELAY}s"
  sleep "$RETRY_DELAY"
done
unset token

log "http_status:    $code"
log "response:"
if jq -e . >/dev/null 2>&1 <<<"$body"; then log "$(jq -S . <<<"$body")"; else log "(non-JSON body, first 300 chars) $(tr -s "[:space:]" " " <<<"$body" | cut -c1-300)"; fi

fail=0
check() { # name, jq filter that must be true
  if jq -e "$2" >/dev/null 2>&1 <<<"$body"; then log "PASS: $1"; else log "FAIL: $1  ($2)"; fail=1; fi
}
[[ "$code" == "200" ]] && log "PASS: HTTP 200" || { log "FAIL: HTTP $code"; fail=1; }
# Contract: app/shared/health.ts (HealthResponse). 200 = ok|degraded, 503 = down.
check "status is ok (not degraded/down)"      '.status == "ok"'
check "version reported"                      '(.version // "") | length > 0'
check "UC probe reachable, no error"          '.unityCatalog.reachable == true and .unityCatalog.error == null'
check "identity is not a human user"          '(.unityCatalog.identity // "") | (length > 0) and (test("@") | not)'
if [[ -n "$sp_app_id" ]]; then
  check "identity == app SP client id ($sp_app_id)" ".unityCatalog.identity == \"$sp_app_id\""
else
  log "FAIL: app has no service_principal_client_id"; fail=1
fi
check "catalog == ${EXPECTED_SCHEMA%%.*}"     ".unityCatalog.catalog == \"${EXPECTED_SCHEMA%%.*}\""
check "schema == ${EXPECTED_SCHEMA#*.}"        ".unityCatalog.schema == \"${EXPECTED_SCHEMA#*.}\""
check "schemaExists == true (live UC query)"  '.unityCatalog.schemaExists == true'
check "probe latency measured"                '(.unityCatalog.latencyMs | type) == "number"'

log ""
[[ $fail -eq 0 ]] && log "SMOKE TEST PASSED" || log "SMOKE TEST FAILED"
exit $fail
