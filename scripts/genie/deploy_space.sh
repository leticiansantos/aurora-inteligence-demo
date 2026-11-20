#!/usr/bin/env bash
# Idempotently create or update the market Genie Agent and print its space id.
# Usage: scripts/genie/deploy_space.sh [--profile P] [--catalog C] [--schema S] [--warehouse W]
set -euo pipefail
PROFILE=classic-stable-new; CATALOG=classic_stable; SCHEMA=auto_intelligence; WAREHOUSE=754bcdfc4beaaaa1
while [ $# -gt 0 ]; do case "$1" in
  --profile) PROFILE=$2; shift 2;; --catalog) CATALOG=$2; shift 2;; --schema) SCHEMA=$2; shift 2;;
  --warehouse) WAREHOUSE=$2; shift 2;; *) echo "unknown arg $1" >&2; exit 2;; esac; done
TITLE="Aurora Motors · Mercado automotivo"
DESC="Emplacamentos do mercado brasileiro (Fenabrave, 2003 em diante) por marca, modelo e segmento, com a Aurora Motors (marca fictícia, dados sintéticos)."
DIR="$(cd "$(dirname "$0")" && pwd)"
ME=$(databricks current-user me --profile "$PROFILE" -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["userName"])')
PARENT="/Workspace/Users/$ME/genie_spaces"
SPACE_JSON=$(python3 "$DIR/build_space.py" "$CATALOG" "$SCHEMA")
SER=$(printf '%s' "$SPACE_JSON" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')
ID=$(databricks genie list-spaces --profile "$PROFILE" -o json | python3 -c "
import json,sys
d=json.load(sys.stdin); sp=d.get('spaces',d) if isinstance(d,dict) else d
print(next((s['space_id'] for s in sp if s.get('title')=='''$TITLE'''),''))")
if [ -n "$ID" ]; then
  databricks genie update-space "$ID" --profile "$PROFILE" --json "{\"title\":\"$TITLE\",\"description\":\"$DESC\",\"warehouse_id\":\"$WAREHOUSE\",\"serialized_space\":$SER}" >/dev/null
  echo "updated $ID" >&2
else
  databricks workspace mkdirs "$PARENT" --profile "$PROFILE"
  ID=$(databricks genie create-space --profile "$PROFILE" -o json --json "{\"title\":\"$TITLE\",\"description\":\"$DESC\",\"warehouse_id\":\"$WAREHOUSE\",\"parent_path\":\"$PARENT\",\"serialized_space\":$SER}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["space_id"])')
  echo "created $ID" >&2
fi
echo "$ID"
