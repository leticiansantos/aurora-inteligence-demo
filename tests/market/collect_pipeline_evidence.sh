#!/usr/bin/env bash
# Read-only evidence of the market pipeline updates -> evidence/market/pipeline-run.txt (ADR D6).
# Lists every update (failed ones included, with their first error), then rows written and expectation
# results per flow for the given updates, read from the pipeline event log via SQL (event_log TVF).
#
# Usage: tests/market/collect_pipeline_evidence.sh <profile> <pipeline_id> <update_id>...
set -uo pipefail

PROFILE="${1:?usage: $0 <profile> <pipeline_id> <update_id>...}"
PIPELINE="${2:?pipeline_id}"
shift 2
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 2
OUT="${MARKET_EVIDENCE_DIR:-evidence/market}"
mkdir -p "$OUT"
SHA="$(git rev-parse --short HEAD)"
NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"
sql() { databricks experimental aitools tools query --profile "$PROFILE" --output csv "$@"; }
redact() { sed -E -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<user>/g' -e "s|$HOME|~|g"; }
EL="event_log('$PIPELINE')"
# warn expectations that are informational by design (ADR R8: unmatched brands are reported, not fixed)
INFO_EXPECTATIONS="'brand_matched'"

fails="$(sql "SELECT count(*) FROM $EL e
  LATERAL VIEW explode(from_json(e.details:flow_progress.data_quality.expectations::string,
    'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>')) x AS ex
  WHERE e.event_type = 'flow_progress' AND e.origin.update_id IN ($(printf "'%s'," "$@" | sed 's/,$//'))
    AND ex.failed_records > 0 AND ex.name NOT IN ($INFO_EXPECTATIONS)" | tail -n1)"

{
  printf '# claim:    pipeline updates %s completed; expectation results per flow (0 failed records except informational brand_matched, reported in quality.txt)\n' "$*"
  printf '# command:  databricks pipelines list-updates %s; SELECT ... FROM event_log(...)\n# git_sha:  %s\n# date:     %s\n' "$PIPELINE" "$SHA" "$NOW"
  printf '# result:   %s\n\n' "$([[ "$fails" == 0 ]] && echo PASS || echo "FAIL ($fails expectation rows with failed records)")"
  echo "## all updates (update_id, state, cause, full_refresh, created)"
  databricks pipelines list-updates "$PIPELINE" --max-results 50 -o json --profile "$PROFILE" \
    | jq -r '.updates[] | [.update_id, .state, .cause, (.full_refresh|tostring), ((.creation_time/1000)|todate)] | @tsv'
  echo; echo "## first error of each failed update"
  sql "SELECT origin.update_id, min(timestamp) AS at, substr(min_by(message, timestamp), 1, 300) AS first_error
       FROM $EL WHERE level = 'ERROR' GROUP BY 1 ORDER BY 2"
  for u in "$@"; do
    echo; echo "## update $u: rows written per flow (COMPLETED)"
    sql "SELECT split(origin.flow_name, '\\\\.')[2] AS flow, details:flow_progress.metrics.num_output_rows::bigint AS rows_out
         FROM $EL WHERE event_type = 'flow_progress' AND details:flow_progress.status = 'COMPLETED' AND origin.update_id = '$u'
         ORDER BY 1"
    echo; echo "## update $u: expectations (flow, expectation, passed, failed)"
    sql "SELECT split(e.origin.flow_name, '\\\\.')[2] AS flow, ex.name AS expectation, ex.passed_records AS passed, ex.failed_records AS failed
         FROM $EL e LATERAL VIEW explode(from_json(e.details:flow_progress.data_quality.expectations::string,
           'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>')) x AS ex
         WHERE e.event_type = 'flow_progress' AND e.origin.update_id = '$u' ORDER BY 1, 2"
  done
} 2>&1 | redact > "$OUT/pipeline-run.txt"
echo "wrote $OUT/pipeline-run.txt (expectation rows with failures: $fails)"
[[ "$fails" == 0 ]]
