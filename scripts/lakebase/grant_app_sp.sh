#!/usr/bin/env bash
# Least-privilege Postgres access for the app service principal (ADR D6):
#  - USAGE on the serving schema + SELECT on the aftersales_lb_* tables only
#  - the SP creates and OWNS aftersales_app itself at startup (no grant, no superuser)
# Run as the project owner AFTER the synced tables are ONLINE and the app ran once. Idempotent.
# Usage: scripts/lakebase/grant_app_sp.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"

SP="$(db apps get "$APP" -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["service_principal_client_id"])')"
[[ -n "$SP" ]] || { echo "Could not resolve service principal of app $APP" >&2; exit 1; }
echo "Granting read on $SYNC_SCHEMA.aftersales_lb_* to $SP"
OWNER="$(db current-user me -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["userName"])')"
pg_exec <<SQL
GRANT USAGE ON SCHEMA $SYNC_SCHEMA TO "$SP";
GRANT SELECT ON $SYNC_SCHEMA.aftersales_lb_dealers, $SYNC_SCHEMA.aftersales_lb_parts,
  $SYNC_SCHEMA.aftersales_lb_forecast_weekly, $SYNC_SCHEMA.aftersales_lb_stockout_risk,
  $SYNC_SCHEMA.aftersales_lb_model_metrics TO "$SP";
-- A SNAPSHOT refresh may recreate the Postgres table: default privileges keep the SELECT grant across syncs.
ALTER DEFAULT PRIVILEGES FOR ROLE "$OWNER" IN SCHEMA $SYNC_SCHEMA GRANT SELECT ON TABLES TO "$SP";
SQL
