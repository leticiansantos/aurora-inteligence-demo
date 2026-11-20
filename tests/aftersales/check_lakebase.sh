#!/usr/bin/env bash
# Lakebase checks for Tela 2 (read-only: every Postgres statement runs in a READ ONLY transaction, and only
# SELECTs go to the SQL warehouse).
#   1. freshness: row count and max(scored_at) of each serving table aftersales_lb_* in Postgres == the Delta source
#   2. content: per-table fingerprints (sums / group counts) Postgres == Delta
#   3. OLTP: partial unique index + CHECK constraints of ${APP_SCHEMA}.aftersales_replenishment_requests, schema owner
#   4. least privilege of the app SP role (ADR 002 D6)
#   5. QA rows (note LIKE 'QA-T6%') listed for the POST round-trip evidence
#
# Usage: tests/aftersales/check_lakebase.sh [app_schema] [out]
#   app_schema: aftersales_app (deployed) | aftersales_app_dev (local validation), default aftersales_app_dev
# Env: PROFILE (classic-stable-new), WAREHOUSE (754bcdfc4beaaaa1), PROJECT_ID (auto-intelligence-aftersales),
#      BRANCH_ID (production), SYNC_SCHEMA (auto_intelligence), SP_ROLE (app SP client id).
set -uo pipefail
APP_SCHEMA="${1:-aftersales_app_dev}"
OUT="${2:-evidence/aftersales/lakebase/checks.txt}"
PROFILE="${PROFILE:-classic-stable-new}"
WAREHOUSE="${WAREHOUSE:-754bcdfc4beaaaa1}"
PROJECT_ID="${PROJECT_ID:-auto-intelligence-aftersales}"
BRANCH_ID="${BRANCH_ID:-production}"
SYNC_SCHEMA="${SYNC_SCHEMA:-auto_intelligence}"
SP_ROLE="${SP_ROLE:-9d41f279-1e55-4654-9579-3587ef47e5e8}"
T="classic_stable.auto_intelligence."
BRANCH="projects/$PROJECT_ID/branches/$BRANCH_ID"
cd "$(git rev-parse --show-toplevel)" || exit 2
mkdir -p "$(dirname "$OUT")"

db() { databricks "$@" --profile "$PROFILE"; }
EP="$(db postgres list-endpoints "$BRANCH" -o json | python3 -c 'import json,sys;e=json.load(sys.stdin);print(e[0]["name"])')" || exit 2
HOST="$(db postgres get-endpoint "$EP" -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"]["hosts"]["host"])')"
USER_NAME="$(db current-user me -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["userName"])')"
export PGPASSWORD
PGPASSWORD="$(db postgres generate-database-credential "$EP" -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')"
pg() { # one value per line, tab separated, in a READ ONLY transaction
  psql "host=$HOST user=$USER_NAME dbname=databricks_postgres sslmode=require" -X -A -t -F $'\t' -v ON_ERROR_STOP=1 \
    -c "BEGIN READ ONLY; $1; COMMIT;" 2>&1 | grep -Ev '^(BEGIN|COMMIT)$'
}
uc() { db experimental aitools tools query -w "$WAREHOUSE" -o csv "$1" 2>&1 | tail -n +2 | tr ',' '\t'; }

FAILS=0; LINES=()
rec() { local ok="$1" label="$2" detail="${3-}"; [ "$ok" = 1 ] || FAILS=$((FAILS+1)); LINES+=("$([ "$ok" = 1 ] && echo PASS || echo FAIL)	$label	$detail"); }
cmp_rec() { # numeric-aware, whitespace-insensitive compare (BSD sed has no \t; CSV may carry \r)
  if python3 -I -c 'import sys
a,b=sys.argv[1].split(),sys.argv[2].split()
def eq(x,y):
    try: return abs(float(x)-float(y))<=1e-6*max(1,abs(float(x)))
    except ValueError: return x==y
sys.exit(0 if len(a)==len(b) and all(eq(x,y) for x,y in zip(a,b)) else 1)' "$(echo "$2" | tr '\t\r' '  ')" "$(echo "$3" | tr '\t\r' '  ')"
  then rec 1 "$1" "pg=$(echo $2) delta=$(echo $3)"; else rec 0 "$1" "pg=$(echo $2) delta=$(echo $3)"; fi; }

# 1+2. freshness and content (fingerprints use rounded sums so float formatting does not matter)
fp_pg() { case "$1" in
  dealers) echo "count(*), round(sum(fleet_share)::numeric, 9)" ;;
  parts) echo "count(*), round(sum(unit_price_brl)::numeric, 4), sum(case when is_critical then 1 else 0 end)" ;;
  forecast_weekly) echo "count(*), round(sum(coalesce(forecast_units,0))::numeric, 3), round(sum(coalesce(actual_units,0))::numeric, 3), date_trunc('second', max(scored_at) AT TIME ZONE 'UTC')" ;;
  stockout_risk) echo "count(*), round(sum(lost_sales_brl)::numeric, 2), sum(recommended_qty), sum(case when action='transfer' then 1 else 0 end), date_trunc('second', max(scored_at) AT TIME ZONE 'UTC')" ;;
  model_metrics) echo "count(*), max(model_version), round(sum(wape)::numeric, 6)" ;;
esac; }
fp_uc() { case "$1" in
  dealers) echo "count(*), round(sum(fleet_share), 9)" ;;
  parts) echo "count(*), round(sum(unit_price_brl), 4), sum(case when is_critical then 1 else 0 end)" ;;
  forecast_weekly) echo "count(*), round(sum(coalesce(forecast_units,0)), 3), round(sum(coalesce(actual_units,0)), 3), date_format(max(scored_at), 'yyyy-MM-dd HH:mm:ss')" ;;
  stockout_risk) echo "count(*), round(sum(lost_sales_brl), 2), sum(recommended_qty), sum(case when action='transfer' then 1 else 0 end), date_format(max(scored_at), 'yyyy-MM-dd HH:mm:ss')" ;;
  model_metrics) echo "count(*), max(model_version), round(sum(wape), 6)" ;;
esac; }
norm() { sed -E 's/\.0+(\t|$)/\1/g; s/(\.[0-9]*[1-9])0+(\t|$)/\1\2/g'; }
for t in dealers parts forecast_weekly stockout_risk model_metrics; do
  p="$(pg "SELECT $(fp_pg $t) FROM \"$SYNC_SCHEMA\".aftersales_lb_$t" | norm)"
  u="$(uc "SELECT $(fp_uc $t) FROM ${T}aftersales_$t" | norm)"
  cmp_rec "aftersales_lb_$t == aftersales_$t (count, sums, max scored_at)" "$p" "$u"
done
pk_of() { case "$1" in dealers) echo dealer_id ;; parts) echo part_id ;; forecast_weekly) echo dealer_id,part_id,week_start ;;
  stockout_risk) echo dealer_id,horizon_days,part_id ;; model_metrics) echo model_version ;; esac; }
for t in dealers parts forecast_weekly stockout_risk model_metrics; do
  pk="$(pg "SELECT string_agg(a.attname, ',' ORDER BY a.attname) FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum = ANY(i.indkey) WHERE i.indisprimary AND i.indrelid = '\"$SYNC_SCHEMA\".aftersales_lb_$t'::regclass")"
  want="$(pk_of $t | tr ',' '\n' | sort | paste -sd, -)"
  [ "$pk" = "$want" ] && rec 1 "aftersales_lb_$t primary key == source PK" "$pk" || rec 0 "aftersales_lb_$t primary key == source PK" "pg=${pk:-none} want=$want"
done
lag="$(uc "SELECT round((unix_timestamp(max(scored_at)) - unix_timestamp((SELECT max(scored_at) FROM ${T}aftersales_forecast_weekly))) / 60, 1) FROM ${T}aftersales_stockout_risk")"
LINES+=("INFO	risk vs forecast scored_at gap (min)	$lag")

# 3. OLTP table
idx="$(pg "SELECT indexdef FROM pg_indexes WHERE schemaname='$APP_SCHEMA' AND tablename='aftersales_replenishment_requests' AND indexdef ILIKE '%unique%' AND indexdef ILIKE '%where%'")"
[[ "$idx" == *dealer_id*part_id*type* && "$idx" == *open*approved*in_transit* ]] && rec 1 "partial unique index (dealer, part, type) on active statuses" "$idx" || rec 0 "partial unique index (dealer, part, type) on active statuses" "${idx:-none}"
chk="$(pg "SELECT string_agg(pg_get_constraintdef(c.oid), ' | ' ORDER BY 1) FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname='$APP_SCHEMA' AND r.relname='aftersales_replenishment_requests' AND c.contype='c'")"
for pat in "reorder" "100000" "from_dealer_id IS NOT NULL" "<> dealer_id" "cancelled" "500"; do
  [[ "$chk" == *"$pat"* ]] && rec 1 "CHECK constraint contains '$pat'" || rec 0 "CHECK constraint contains '$pat'" "$chk"
done
owner="$(pg "SELECT nspowner::regrole FROM pg_namespace WHERE nspname='$APP_SCHEMA'")"
LINES+=("INFO	owner of schema $APP_SCHEMA	$(echo "$owner" | sed -E 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+/<user>/g')")
if [ "$APP_SCHEMA" = aftersales_app ]; then
  [ "$owner" = "$SP_ROLE" ] && rec 1 "aftersales_app owned by the app SP" || rec 0 "aftersales_app owned by the app SP" "owner=$owner"
fi
pii="$(pg "SELECT count(*) FROM \"$APP_SCHEMA\".aftersales_replenishment_requests WHERE requested_by NOT IN ('app','local-dev') OR requested_by LIKE '%@%'")"
[ "$pii" = 0 ] && rec 1 "requested_by only 'app'/'local-dev' (no PII)" || rec 0 "requested_by only 'app'/'local-dev' (no PII)" "rows=$pii"

# 4. least privilege of the app SP role
exists="$(pg "SELECT count(*) FROM pg_roles WHERE rolname='$SP_ROLE'")"
if [ "$exists" = 1 ]; then
  sup="$(pg "SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls FROM pg_roles WHERE rolname='$SP_ROLE'")"
  [ "$sup" = f ] && rec 1 "SP role: not superuser/createrole/createdb/bypassrls" || rec 0 "SP role: not superuser/createrole/createdb/bypassrls" "$sup"
  mem="$(pg "SELECT string_agg(b.rolname, ',') FROM pg_auth_members m JOIN pg_roles b ON b.oid=m.roleid JOIN pg_roles u ON u.oid=m.member WHERE u.rolname='$SP_ROLE'")"
  [[ "$mem" != *databricks_superuser* ]] && rec 1 "SP role: not member of databricks_superuser" "member_of=${mem:-none}" || rec 0 "SP role: not member of databricks_superuser" "$mem"
  for t in dealers parts forecast_weekly stockout_risk model_metrics; do
    priv="$(pg "SELECT has_table_privilege('$SP_ROLE', '\"$SYNC_SCHEMA\".aftersales_lb_$t', 'SELECT')::text || ',' || (has_table_privilege('$SP_ROLE', '\"$SYNC_SCHEMA\".aftersales_lb_$t', 'INSERT') OR has_table_privilege('$SP_ROLE', '\"$SYNC_SCHEMA\".aftersales_lb_$t', 'UPDATE') OR has_table_privilege('$SP_ROLE', '\"$SYNC_SCHEMA\".aftersales_lb_$t', 'DELETE') OR has_table_privilege('$SP_ROLE', '\"$SYNC_SCHEMA\".aftersales_lb_$t', 'TRUNCATE'))::text")"
    [ "$priv" = "true,false" ] && rec 1 "SP: SELECT only on aftersales_lb_$t" || rec 0 "SP: SELECT only on aftersales_lb_$t" "select,write=$priv"
  done
  cr="$(pg "SELECT has_schema_privilege('$SP_ROLE', '$SYNC_SCHEMA', 'CREATE')")"
  [ "$cr" = f ] && rec 1 "SP: no CREATE on serving schema $SYNC_SCHEMA" || rec 0 "SP: no CREATE on serving schema $SYNC_SCHEMA" "$cr"
  other="$(pg "SELECT count(*) FROM information_schema.role_table_grants WHERE grantee='$SP_ROLE' AND table_schema NOT IN ('$SYNC_SCHEMA','$APP_SCHEMA')")"
  [ "$other" = 0 ] && rec 1 "SP: no table grants outside serving/app schemas" || rec 0 "SP: no table grants outside serving/app schemas" "n=$other"
else
  LINES+=("DEFERRED	SP role $SP_ROLE not in Postgres: app deploy with the postgres resource is follow-up F1 (ADR D8 step 6); not a failure	")
fi

# 5. QA rows
LINES+=("INFO	QA-T6 request rows (id, dealer, part, type, qty, status, requested_by, horizon, risk_level, lost_sales, forecast_date)	")
while IFS= read -r l; do [ -n "$l" ] && LINES+=("ROW	$l"); done < <(pg "SELECT id, dealer_id, part_id, type, quantity, status, requested_by, horizon_days, risk_level, lost_sales_brl, forecast_date FROM \"$APP_SCHEMA\".aftersales_replenishment_requests WHERE note LIKE 'QA-T6%' ORDER BY created_at")

{
  echo "# claim:   Lakebase serving tables match Delta; OLTP constraints and app SP least privilege per ADR 002 D6"
  echo "# command: tests/aftersales/check_lakebase.sh $APP_SCHEMA"
  echo "# project: $BRANCH  serving schema: $SYNC_SCHEMA  app schema: $APP_SCHEMA"
  echo "# date:    $(date -u '+%Y-%m-%d %H:%M UTC')  qa git: $(git rev-parse --short HEAD)"
  echo "# result:  $([ $FAILS = 0 ] && echo PASS || echo "FAIL ($FAILS)")"
  echo
  printf '%s\n' "${LINES[@]}"
} | sed -E 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<user>/g' | tee "$OUT"
[ $FAILS = 0 ]
