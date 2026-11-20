#!/usr/bin/env bash
# Grant the app's auto-created service principal least-privilege access to the demo schema.
# Idempotent: UC `grants update` only adds the listed privileges, so re-runs are no-ops.
# Also adds an explicit CAN_USE entry for the SP on the warehouse and asserts it.
#
# Usage: scripts/grant_app_sp.sh [--profile P] [--app NAME] [--catalog C] [--schema S] [--warehouse-id W]
set -euo pipefail

PROFILE="classic-stable-new"
APP="auto-intelligence"
CATALOG="classic_stable"
SCHEMA="auto_intelligence"
WAREHOUSE_ID="754bcdfc4beaaaa1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --app) APP="$2"; shift 2 ;;
    --catalog) CATALOG="$2"; shift 2 ;;
    --schema) SCHEMA="$2"; shift 2 ;;
    --warehouse-id) WAREHOUSE_ID="$2"; shift 2 ;;
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

db() { databricks "$@" --profile "$PROFILE"; }

SP_CLIENT_ID="$(db apps get "$APP" -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["service_principal_client_id"])')"
[[ -n "$SP_CLIENT_ID" ]] || { echo "Could not resolve the service principal of app $APP" >&2; exit 1; }
echo "App $APP service principal: $SP_CLIENT_ID"

grant() { # <securable_type> <full_name> <privilege>...
  local type="$1" name="$2"; shift 2
  local privs; privs="$(printf '"%s",' "$@")"; privs="[${privs%,}]"
  db grants update "$type" "$name" \
    --json "{\"changes\":[{\"principal\":\"$SP_CLIENT_ID\",\"add\":$privs}]}" >/dev/null
  echo "Ensured $* on $type $name (grants update is additive)"
}

# Least privilege: browse the catalog, read tables and volumes of this one schema only.
grant catalog "$CATALOG" USE_CATALOG
grant schema "$CATALOG.$SCHEMA" USE_SCHEMA SELECT READ_VOLUME

# Warehouse CAN_USE: add an explicit ACL entry for the SP (the `users` group alone is not enough
# to prove the app's own access). update-permissions is a PATCH: it only adds this entry and never
# drops existing ones. Report "unchanged" vs "granted" from the ACL itself, then assert.
has_sp_entry() {
  db warehouses get-permissions "$WAREHOUSE_ID" -o json | SP="$SP_CLIENT_ID" python3 -c '
import json, os, sys
sp = os.environ["SP"]
ok = any(e.get("service_principal_name") == sp and
         any(p.get("permission_level") in ("CAN_USE", "CAN_MANAGE") for p in e.get("all_permissions", []))
         for e in json.load(sys.stdin).get("access_control_list", []))
sys.exit(0 if ok else 1)'
}

if has_sp_entry; then
  echo "Warehouse $WAREHOUSE_ID: CAN_USE for app service principal unchanged"
else
  db warehouses update-permissions "$WAREHOUSE_ID" \
    --json "{\"access_control_list\":[{\"service_principal_name\":\"$SP_CLIENT_ID\",\"permission_level\":\"CAN_USE\"}]}" >/dev/null
  echo "Warehouse $WAREHOUSE_ID: CAN_USE granted to app service principal"
fi
has_sp_entry || { echo "ERROR: app service principal has no explicit CAN_USE on warehouse $WAREHOUSE_ID" >&2; exit 1; }
