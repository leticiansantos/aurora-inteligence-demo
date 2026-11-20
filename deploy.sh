#!/usr/bin/env bash
# One-command, re-runnable deploy: validate -> bundle deploy -> grants -> Lakebase (aftersales) -> run app -> smoke test.
#
# Usage: ./deploy.sh [--profile P] [--target demo|dev] [--skip-smoke]
# Defaults: profile classic-stable-new, target demo. No other profile is ever selected implicitly.
set -euo pipefail

PROFILE="classic-stable-new"
TARGET="demo"
SMOKE=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --target|-t) TARGET="$2"; shift 2 ;;
    --skip-smoke) SMOKE=0; shift ;;
    -h|--help) sed -n 2,6p "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")"
echo "==> profile=$PROFILE target=$TARGET"

step() { echo; echo "==> $*"; }

step "Validate bundle"
databricks bundle validate --strict -t "$TARGET" --profile "$PROFILE"

step "Deploy bundle (schema, volumes, app)"
databricks bundle deploy -t "$TARGET" --profile "$PROFILE"

# Resolve names and ids from the deployed bundle instead of hardcoding them.
SUMMARY="$(databricks bundle summary -t "$TARGET" --profile "$PROFILE" -o json)"
jget() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))' "$1" <<<"$SUMMARY"; }
APP_NAME="$(jget 'd["resources"]["apps"]["app"]["name"]')"
SCHEMA="$(jget 'd["resources"]["schemas"]["demo_schema"]["name"]')"
CATALOG="$(jget 'd["resources"]["schemas"]["demo_schema"]["catalog_name"]')"

step "Grant app service principal (least privilege)"
scripts/grant_app_sp.sh --profile "$PROFILE" --app "$APP_NAME" --catalog "$CATALOG" --schema "$SCHEMA"

# Aftersales Lakebase (ADR 002 D6/D8): CLI-managed, idempotent. The synced tables need the ML tables, which the
# job `aftersales_daily` creates; on a fresh environment run the job first, then re-run this script.
step "Lakebase project (aftersales)"
PROFILE="$PROFILE" scripts/lakebase/create_project.sh
if [[ "$(databricks tables exists "$CATALOG.$SCHEMA.aftersales_stockout_risk" --profile "$PROFILE" -o json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("table_exists", False))')" == "True" ]]; then
  step "Lakebase synced tables (aftersales_lb_*)"
  PROFILE="$PROFILE" UC_CATALOG="$CATALOG" UC_SCHEMA="$SCHEMA" scripts/lakebase/sync_tables.sh
else
  echo "aftersales_stockout_risk not found: run 'databricks bundle run aftersales_daily -t $TARGET' and re-run deploy.sh"
fi

step "Deploy and start app source"
# `bundle run app` creates a new app deployment every time, so skip it when the app source and
# config are unchanged since the last successful run and the app is already running.
mkdir -p .databricks
HASH_FILE=".databricks/deploy-${TARGET}.hash"
CURRENT_HASH="$( { find app -type f -not -path '*/node_modules/*' -not -path '*/dist/*' -not -path '*/.databricks/*' -print0 \
  | sort -z | xargs -0 shasum; shasum databricks.yml resources/*.yml; } | shasum | cut -d' ' -f1)"
APP_STATE="$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("app_status",{}).get("state",""), d.get("active_deployment",{}).get("status",{}).get("state",""))')"
if [[ -f "$HASH_FILE" && "$(cat "$HASH_FILE")" == "$CURRENT_HASH" && "$APP_STATE" == "RUNNING SUCCEEDED" ]]; then
  echo "App source unchanged and running: skipping app deployment"
else
  databricks bundle run app -t "$TARGET" --profile "$PROFILE"
  echo "$CURRENT_HASH" > "$HASH_FILE"
fi

if [[ "$SMOKE" -eq 1 ]]; then
  step "Smoke test /api/health"
  tests/smoke/health_smoke.sh "$PROFILE" "$APP_NAME" --schema "$CATALOG.$SCHEMA"
fi

echo; echo "Done: $APP_NAME ($TARGET)"
