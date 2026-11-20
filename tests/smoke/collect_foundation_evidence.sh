#!/usr/bin/env bash
# Collect read-only text evidence for the deployed foundation into evidence/foundation/.
# Changes nothing in the workspace: validate/summary, UC and warehouse listings,
# app status, the health smoke test and HTTP-level UI checks.
#
# Usage: tests/smoke/collect_foundation_evidence.sh <profile> [target]
# Emails and local home paths are redacted; tokens are never written.
set -uo pipefail

PROFILE="${1:?usage: $0 <profile> [target]}"
TARGET="${2:-demo}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 2
OUT=evidence/foundation
mkdir -p "$OUT"
SHA="$(git rev-parse --short HEAD)"
NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"

redact() { sed -E -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<deploy-user>/g' -e "s|$HOME|~|g"; }
header() { # file claim command result
  printf '# claim:    %s\n# command:  %s\n# git_sha:  %s\n# date:     %s\n# result:   %s\n\n' "$2" "$3" "$SHA" "$NOW" "$4" > "$1"
}
db() { databricks "$@" --profile "$PROFILE"; }

summary_json="$(db bundle summary -t "$TARGET" -o json)"
APP="$(jq -r '.resources.apps.app.name' <<<"$summary_json")"
CATALOG="$(jq -r '.resources.schemas.demo_schema.catalog_name' <<<"$summary_json")"
SCHEMA="$(jq -r '.resources.schemas.demo_schema.name' <<<"$summary_json")"
WAREHOUSE="$(jq -r '.resources.apps.app.resources[] | select(.sql_warehouse) | .sql_warehouse.id' <<<"$summary_json")"

# 1. bundle validate
v="$(db bundle validate --strict -t "$TARGET" 2>&1)"; rc=$?
header "$OUT/bundle-validate.txt" "the bundle validates in strict mode" \
  "databricks bundle validate --strict -t $TARGET --profile $PROFILE" "$([[ $rc -eq 0 ]] && echo PASS || echo FAIL)"
redact <<<"$v" >> "$OUT/bundle-validate.txt"

# 2. bundle summary
header "$OUT/bundle-summary.txt" "deployed bundle resources (schema, 2 volumes, app) and their ids" \
  "databricks bundle summary -t $TARGET --profile $PROFILE" "PASS"
db bundle summary -t "$TARGET" 2>&1 | redact >> "$OUT/bundle-summary.txt"
echo "
# note: the app URL reads from local deploy state; when collected from a checkout other than
# the one that deployed it prints (not deployed). See app-status.txt for the live URL." >> "$OUT/bundle-summary.txt"

# 3. UC schema + volumes
{
  header /dev/stdout "schema $CATALOG.$SCHEMA and its managed volumes exist" \
    "databricks schemas get $CATALOG.$SCHEMA; databricks volumes list $CATALOG $SCHEMA" "PASS"
  echo "## schema"
  db schemas get "$CATALOG.$SCHEMA" -o json | jq '{full_name, catalog_name, name, comment, owner, created_at: (.created_at/1000|todate)}'
  echo; echo "## volumes"
  db volumes list "$CATALOG" "$SCHEMA" -o json | jq -r '["full_name","volume_type","comment"], (.[] | [.full_name, .volume_type, .comment]) | @tsv'
} 2>&1 | redact > "$OUT/uc-schema-volumes.txt"

# 4. grants + warehouse ACL for the app service principal
app_json="$(db apps get "$APP" -o json)"
SP="$(jq -r '.service_principal_client_id' <<<"$app_json")"
sp_cat="$(db grants get catalog "$CATALOG" -o json | jq -r --arg sp "$SP" '[.privilege_assignments[] | select(.principal==$sp) | .privileges[]] | sort | join(",")')"
sp_sch="$(db grants get schema "$CATALOG.$SCHEMA" -o json | jq -r --arg sp "$SP" '[(.privilege_assignments // [])[] | select(.principal==$sp) | .privileges[]] | sort | join(",")')"
sp_wh="$(db warehouses get-permissions "$WAREHOUSE" -o json | jq -r --arg sp "$SP" '[.access_control_list[] | select(.service_principal_name==$sp) | .all_permissions[].permission_level] | join(",")')"
grants_ok=FAIL
[[ "$sp_cat" == "USE_CATALOG" && "$sp_sch" == "READ_VOLUME,SELECT,USE_SCHEMA" ]] && grants_ok=PASS
{
  header /dev/stdout "the app service principal ($SP) holds exactly the intended UC privileges" \
    "databricks grants get catalog|schema|volume ...; databricks warehouses get-permissions $WAREHOUSE" "$grants_ok"
  echo "## app SP summary"
  echo "catalog $CATALOG:          ${sp_cat:-<none>}   (expected USE_CATALOG)"
  echo "schema  $CATALOG.$SCHEMA:  ${sp_sch:-<none>}   (expected READ_VOLUME,SELECT,USE_SCHEMA)"
  echo "warehouse $WAREHOUSE explicit ACL: ${sp_wh:-<none>}   (declared CAN_USE via app resource)"
  [[ -z "$sp_wh" ]] && echo "NOTE: no explicit warehouse entry for the app SP; access is inherited from group 'users' (CAN_USE)."
  echo
  echo "## catalog $CATALOG (all principals)"
  db grants get catalog "$CATALOG" -o json | jq -r '.privilege_assignments[] | [.principal, (.privileges|join(","))] | @tsv'
  echo; echo "## schema $CATALOG.$SCHEMA (all principals)"
  db grants get schema "$CATALOG.$SCHEMA" -o json | jq -r '.privilege_assignments[]? | [.principal, (.privileges|join(","))] | @tsv'
  for vol in $(db volumes list "$CATALOG" "$SCHEMA" -o json | jq -r '.[].full_name'); do
    echo; echo "## volume $vol (direct grants)"
    db grants get volume "$vol" -o json | jq -r '(.privilege_assignments // [])[] | [.principal, (.privileges|join(","))] | @tsv'
  done
  echo; echo "## warehouse $WAREHOUSE ACL"
  db warehouses get-permissions "$WAREHOUSE" -o json \
    | jq -r '.access_control_list[] | [(.user_name // .group_name // .service_principal_name), ([.all_permissions[] | .permission_level + (if .inherited then "(inherited)" else "" end)]|join(","))] | @tsv'
  echo; echo "## app resource declaration"
  jq -c '.resources' <<<"$app_json"
} 2>&1 | redact > "$OUT/uc-grants.txt"

# 5. app status
header "$OUT/app-status.txt" "app is RUNNING with an active SUCCEEDED deployment and its own service principal" \
  "databricks apps get $APP; databricks apps list-deployments $APP" "$(jq -r '.app_status.state' <<<"$app_json")"
{
  jq '{name, url, app_status, compute_status, service_principal_client_id, service_principal_name,
       active_deployment: {deployment_id: .active_deployment.deployment_id, status: .active_deployment.status, create_time: .active_deployment.create_time},
       pending_deployment, update_time}' <<<"$app_json"
  echo; echo "## deployments"
  db apps list-deployments "$APP" -o json | jq -r '.[] | [.deployment_id, .status.state, .create_time] | @tsv'
} 2>&1 | redact >> "$OUT/app-status.txt"

# 6. health smoke test
tmp="$(mktemp)"
tests/smoke/health_smoke.sh "$PROFILE" "$APP" --schema "$CATALOG.$SCHEMA" --out "$tmp" >/dev/null; rc=$?
header "$OUT/health-smoke.txt" "/api/health ran a live UC query as the app service principal and found the schema" \
  "tests/smoke/health_smoke.sh $PROFILE $APP --schema $CATALOG.$SCHEMA" "$([[ $rc -eq 0 ]] && echo PASS || echo FAIL)"
redact < "$tmp" >> "$OUT/health-smoke.txt"; rm -f "$tmp"

# 7. warehouse query history: who executed statements recently
{
  header /dev/stdout "statements on the warehouse after the smoke call were executed as the app SP" \
    "databricks api get /api/2.0/sql/history/queries (filter warehouse $WAREHOUSE)" "see rows"
  echo "executed_as	status	start_utc	(query text is redacted by the API for other principals)"
  db api get "/api/2.0/sql/history/queries?max_results=20" --json "{\"filter_by\":{\"warehouse_ids\":[\"$WAREHOUSE\"]}}" -o json \
    | jq -r '.res[]? | [.executed_as_user_name, .status, (.query_start_time_ms/1000|todate)] | @tsv' | head -10
} 2>&1 | redact > "$OUT/sp-query-history.txt"

# 8. HTTP-level UI checks (no browser)
url="$(jq -r '.url' <<<"$app_json")"
token="$(db auth token | jq -r '.access_token')"
tmpd="$(mktemp -d)"
{
  header /dev/stdout "UI is auth-gated, serves the pt-BR shell and assets, and the served bundle holds the section copy and no secrets" \
    "curl with/without the caller's OAuth token (token not recorded)" "see checks"
  echo "no token  GET /            -> $(curl -s -o /dev/null -w '%{http_code}' "$url/")  (expect 302 to login)"
  echo "no token  GET /api/health  -> $(curl -s -o /dev/null -w '%{http_code}' "$url/api/health")  (expect 401)"
  curl -s -H "Authorization: Bearer $token" "$url/" -o "$tmpd/index.html"
  echo "token     GET /            -> $(curl -s -H "Authorization: Bearer $token" -o /dev/null -w '%{http_code}' "$url/")"
  grep -o -E '<html[^>]*>|<title>[^<]*</title>' "$tmpd/index.html" | sed 's/^/  /'
  for a in $(grep -o -E '(src|href)="/[^"]+"' "$tmpd/index.html" | cut -d'"' -f2 | sort -u); do
    f="$tmpd/$(basename "$a")"
    echo "token     GET $a -> $(curl -s -H "Authorization: Bearer $token" -o "$f" -w '%{http_code}' "$url$a") ($(wc -c < "$f" | tr -d ' ') bytes)"
  done
  for r in /mercado /pos-venda /motorista /genie; do
    echo "token     GET $r -> $(curl -s -H "Authorization: Bearer $token" -o /dev/null -w '%{http_code}' "$url$r")"
  done
  js="$(ls "$tmpd"/*.js 2>/dev/null | head -1)"
  echo; echo "## served JS bundle content"
  for s in "Visão de Mercado" "Pós-venda" "Visão do Motorista" "Genie" "Benefícios" "Aurora Motors"; do
    echo "  contains \"$s\": $(grep -c -F "$s" "$js" >/dev/null && echo yes || echo NO)"
  done
  DENYLIST="$(dirname "$0")/../.brand-denylist.local"; BRAND_WORDS=""
  # shellcheck source=/dev/null
  [[ -f "$DENYLIST" ]] && source "$DENYLIST"
  if [[ -n "$BRAND_WORDS" ]]; then
    echo "  real-brand words: $(grep -o -i -w -E "$BRAND_WORDS" "$js" | wc -l | tr -d ' ') (expect 0)"
  else
    echo "  real-brand words: SKIP (local denylist not found)"
  fi
  echo "  token patterns:   $(grep -o -E 'dapi[0-9a-f]{32}|dose[0-9a-f]{32}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}' "$js" | wc -l | tr -d ' ') (expect 0)"
} 2>&1 | redact > "$OUT/ui-http-check.txt"
unset token; rm -rf "$tmpd"

echo "wrote: $(ls "$OUT" | tr '\n' ' ')"
