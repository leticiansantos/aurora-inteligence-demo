#!/usr/bin/env bash
# Collect read-only text evidence for one run of the market job (no runs are started here).
#
# Usage: tests/market/collect_run_evidence.sh <profile> <job_run_id> <label> [target]
#   label: e.g. run1 / run2 -> evidence/market/job-<label>.txt (task states, has_new_files outcome,
#          download output, pipeline update state and expectations), plus evidence/market/job-schedule.txt.
# For the idempotency run (run2) the claim checked is: has_new_files outcome false and pipeline task skipped.
set -uo pipefail

PROFILE="${1:?usage: $0 <profile> <job_run_id> <label> [target]}"
RUN_ID="${2:?job_run_id}"
LABEL="${3:?label}"
TARGET="${4:-demo}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 2
OUT="${MARKET_EVIDENCE_DIR:-evidence/market}"
mkdir -p "$OUT"
SHA="$(git rev-parse --short HEAD)"
NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"
db() { databricks "$@" --profile "$PROFILE"; }
redact() { sed -E -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<user>/g' -e "s|$HOME|~|g"; }

run_json="$(db jobs get-run "$RUN_ID" -o json)" || { echo "cannot read run $RUN_ID" >&2; exit 2; }
JOB_ID="$(jq -r '.job_id' <<<"$run_json")"
tasks="$(jq -r '.tasks[] | [.task_key, (.state.life_cycle_state // "-"), (.state.result_state // "-"),
  (.condition_task.outcome // "-"), (.run_id|tostring)] | @tsv' <<<"$run_json")"
cond_outcome="$(jq -r '[.tasks[] | select(.condition_task) | .condition_task.outcome][0] // "none"' <<<"$run_json")"
pipe_state="$(jq -r '[.tasks[] | select(.pipeline_task) | (.state.result_state // .state.life_cycle_state)][0] // "none"' <<<"$run_json")"

if [[ "$LABEL" == run1 ]]; then
  claim="first job run: download task succeeded, pipeline task ran and succeeded"
  pass=$([[ "$(jq -r '.state.result_state' <<<"$run_json")" == SUCCESS && "$pipe_state" == SUCCESS ]] && echo PASS || echo FAIL)
else
  claim="re-run: has_new_files outcome is false and the pipeline task is skipped (no new downloads)"
  pass=$([[ "$cond_outcome" == false && ( "$pipe_state" == EXCLUDED || "$pipe_state" == SKIPPED ) ]] && echo PASS || echo FAIL)
fi

{
  printf '# claim:    %s\n# command:  databricks jobs get-run %s; jobs get-run-output; pipelines get-update / list-pipeline-events\n# target:   %s\n# git_sha:  %s\n# date:     %s\n# result:   %s\n\n' \
    "$claim" "$RUN_ID" "$TARGET" "$SHA" "$NOW" "$pass"
  echo "## run"
  jq -r '"job_id=\(.job_id) run_id=\(.run_id) trigger=\(.trigger) state=\(.state.life_cycle_state)/\(.state.result_state // "-") start=\((.start_time/1000)|todate) duration_s=\(((.run_duration // .execution_duration // 0)/1000))"' <<<"$run_json"
  echo; echo "## tasks (task_key, life_cycle_state, result_state, condition_outcome, task_run_id)"
  echo "$tasks"
  echo; echo "## condition outcome: $cond_outcome · pipeline task: $pipe_state"
  dl_run="$(jq -r '[.tasks[] | select(.task_key=="download") | .run_id][0] // empty' <<<"$run_json")"
  if [[ -n "$dl_run" ]]; then
    echo; echo "## download task output (logs tail + task values)"
    db jobs get-run-output "$dl_run" -o json | jq -r '(.logs // "" | split("\n") | .[-60:] | join("\n")), "error=\(.error // "-")"'
  fi
  upd="$(jq -r '[.tasks[] | select(.pipeline_task) | .pipeline_task.pipeline_id][0] // empty' <<<"$run_json")"
  if [[ -n "$upd" && "$pipe_state" != EXCLUDED && "$pipe_state" != SKIPPED ]]; then
    echo; echo "## pipeline $upd: latest updates"
    db pipelines list-updates "$upd" -o json | jq -r '.updates[:3][] | [.update_id, .state, .cause, (.full_refresh|tostring), ((.creation_time/1000)|todate)] | @tsv'
    echo; echo "## pipeline flow progress (rows written, expectation results) for the latest update"
    db pipelines list-pipeline-events "$upd" --max-results 250 -o json \
      | jq -r '[.[] | select(.event_type=="flow_progress" and .details.flow_progress.status=="COMPLETED")]
               | .[] | [.origin.flow_name,
                        (.details.flow_progress.metrics.num_output_rows // "-" | tostring),
                        ((.details.flow_progress.data_quality.expectations // []) | map("\(.name): pass=\(.passed_records) fail=\(.failed_records)") | join("; "))] | @tsv' \
      | sort -u
  fi
} 2>&1 | redact > "$OUT/job-$LABEL.txt"

{
  printf '# claim:    the market job schedule ships PAUSED (runs are triggered manually)\n# command:  databricks jobs get %s\n# git_sha:  %s\n# date:     %s\n' "$JOB_ID" "$SHA" "$NOW"
  job_json="$(db jobs get "$JOB_ID" -o json)"
  ps="$(jq -r '.settings.schedule.pause_status // "NO_SCHEDULE"' <<<"$job_json")"
  printf '# result:   %s\n\n' "$([[ "$ps" == PAUSED ]] && echo PASS || echo FAIL)"
  jq -r '{name: .settings.name, schedule: .settings.schedule, tasks: [.settings.tasks[] | {task_key, depends_on, condition_task, pipeline_task}]}' <<<"$job_json"
} 2>&1 | redact > "$OUT/job-schedule.txt"
echo "wrote $OUT/job-$LABEL.txt ($pass), $OUT/job-schedule.txt"
[[ "$pass" == PASS ]]
