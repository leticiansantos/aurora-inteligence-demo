#!/usr/bin/env bash
# Shared settings/helpers for the Lakebase scripts (source this file).
PROFILE="${PROFILE:-classic-stable-new}"
PROJECT_ID="${PROJECT_ID:-auto-intelligence-aftersales}"
BRANCH_ID="${BRANCH_ID:-production}"
PG_DATABASE="${PG_DATABASE:-databricks_postgres}"
UC_CATALOG="${UC_CATALOG:-classic_stable}"        # regular catalog: source tables + sync pipeline metadata
UC_SCHEMA="${UC_SCHEMA:-auto_intelligence}"
SYNC_SCHEMA="${SYNC_SCHEMA:-auto_intelligence}"   # Postgres schema holding the serving tables aftersales_lb_*
APP="${APP:-auto-intelligence}"
BRANCH="projects/$PROJECT_ID/branches/$BRANCH_ID"

db() { databricks "$@" --profile "$PROFILE"; }

endpoint_path() {
  db postgres list-endpoints "$BRANCH" -o json | python3 -c '
import json,sys
eps=json.load(sys.stdin)
rw=[e for e in eps if e.get("status",{}).get("endpoint_type","ENDPOINT_TYPE_READ_WRITE").endswith("READ_WRITE")] or eps
print(rw[0]["name"])'
}

# Runs SQL against the Lakebase database as the caller (project owner). Reads SQL from stdin.
pg_exec() {
  local ep host token user
  ep="$(endpoint_path)"
  host="$(db postgres get-endpoint "$ep" -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"]["hosts"]["host"])')"
  token="$(db postgres generate-database-credential "$ep" -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')"
  user="$(db current-user me -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["userName"])')"
  PGPASSWORD="$token" psql "host=$host user=$user dbname=$PG_DATABASE sslmode=require" -v ON_ERROR_STOP=1 -q "$@"
}
