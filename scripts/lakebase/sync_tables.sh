#!/usr/bin/env bash
# Plan A (ADR D6): create (idempotently) the Lakebase synced tables, SNAPSHOT mode.
# Synced table ID = <uc_catalog>.<uc_schema>.aftersales_lb_<entity> -> Postgres table
# <uc_schema>.aftersales_lb_<entity>. Source: <uc_catalog>.<uc_schema>.aftersales_<entity>.
# Needs a UC *view/table* named aftersales_lb_<entity> to be creatable in the schema; pipeline metadata
# is stored in the same catalog/schema. Re-sync after each scoring run: src/aftersales/serving/refresh_synced_tables.py.
# Usage: scripts/lakebase/sync_tables.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"

# Frozen contract: docs/data-model/aftersales.md (section Lakebase). entity:primary_key_columns
TABLES=(
  "dealers:dealer_id"
  "parts:part_id"
  "forecast_weekly:dealer_id,part_id,week_start"
  "stockout_risk:dealer_id,part_id,horizon_days"
  "model_metrics:model_version"
)

# Pass 1 (read-only): classify every table so a transient error never creates anything and a failure
# aborts BEFORE a partial set is created. Pass 2 creates the missing ones.
missing=()
for entry in "${TABLES[@]}"; do
  entity="${entry%%:*}"
  target="$UC_CATALOG.$UC_SCHEMA.aftersales_lb_$entity"
  if out="$(db postgres get-synced-table "synced_tables/$target" -o json 2>&1)"; then
    # Validate what exists: it must read from the contracted source and use SNAPSHOT.
    echo "$out" | grep -q "$UC_CATALOG.$UC_SCHEMA.aftersales_$entity\"" || { echo "ERROR: $target has an unexpected source table" >&2; exit 1; }
    echo "$out" | grep -q "SNAPSHOT" || { echo "ERROR: $target is not SNAPSHOT" >&2; exit 1; }
    echo "Synced table $target already exists and matches the contract"
  elif echo "$out" | grep -q "TABLE_DOES_NOT_EXIST\|does not exist\|NOT_FOUND"; then
    missing+=("$entry")
  else
    echo "ERROR: cannot read $target: $out" >&2; exit 1
  fi
done

for entry in ${missing[@]+"${missing[@]}"}; do
  entity="${entry%%:*}"; pk_csv="${entry##*:}"
  target="$UC_CATALOG.$UC_SCHEMA.aftersales_lb_$entity"
  pk_json="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1].split(",")))' "$pk_csv")"
  echo "Creating $target"
  db postgres create-synced-table "$target" --json "{\"spec\":{
    \"source_table_full_name\":\"$UC_CATALOG.$UC_SCHEMA.aftersales_$entity\",
    \"primary_key_columns\":$pk_json,
    \"scheduling_policy\":\"SNAPSHOT\",
    \"branch\":\"$BRANCH\",
    \"postgres_database\":\"$PG_DATABASE\",
    \"create_database_objects_if_missing\":true,
    \"new_pipeline_spec\":{\"storage_catalog\":\"$UC_CATALOG\",\"storage_schema\":\"$UC_SCHEMA\"}}}"
done
