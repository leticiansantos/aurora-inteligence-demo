#!/usr/bin/env bash
# Idempotently create the Lakebase project (smallest, scale-to-zero). No UC catalog is registered
# (no CREATE CATALOG privilege; see ADR D6): synced tables use existing classic_stable.auto_intelligence.
# Usage: scripts/lakebase/create_project.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"

if db postgres get-project "projects/$PROJECT_ID" -o json >/dev/null 2>&1; then
  echo "Project $PROJECT_ID already exists"
else
  db postgres create-project "$PROJECT_ID" --json '{"spec":{"display_name":"Auto Intelligence - Pos-venda",
    "default_endpoint_settings":{"autoscaling_limit_min_cu":0.5,"autoscaling_limit_max_cu":1,"suspend_timeout_duration":"300s"}}}'
fi
