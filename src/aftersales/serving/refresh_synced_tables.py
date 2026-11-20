"""Job task `sync`: refresh the Lakebase synced tables (SNAPSHOT) after each scoring run.

Plan A of ADR D6: every synced table is backed by a managed pipeline; a SNAPSHOT table only re-syncs when
its pipeline is started. For each table we locate the pipeline from the synced-table resource, start an
update and wait for it. Tables that do not exist yet are skipped (first run happens before
scripts/lakebase/sync_tables.sh), so the job stays green on a fresh environment.

Usage (job parameters): --catalog classic_stable --schema auto_intelligence [--timeout-s 1800]
Requires databricks-sdk (preinstalled on serverless). NOT yet exercised against a live synced table:
the pipeline-id lookup is defensive (searches the resource for `pipeline_id`).
"""

from __future__ import annotations

import argparse
import time
from typing import Any

ENTITIES = ["dealers", "parts", "forecast_weekly", "stockout_risk", "model_metrics"]
TERMINAL_OK = {"COMPLETED"}
TERMINAL_BAD = {"FAILED", "CANCELED"}


def synced_table_name(catalog: str, schema: str, entity: str) -> str:
    return f"{catalog}.{schema}.aftersales_lb_{entity}"


def find_pipeline_id(resource: Any) -> str | None:
    """Depth-first search for the first non-empty `pipeline_id` in a synced-table resource."""
    if isinstance(resource, dict):
        value = resource.get("pipeline_id")
        if isinstance(value, str) and value:
            return value
        for child in resource.values():
            found = find_pipeline_id(child)
            if found:
                return found
    elif isinstance(resource, list):
        for child in resource:
            found = find_pipeline_id(child)
            if found:
                return found
    return None


def update_state(update_response: dict[str, Any]) -> str | None:
    return (update_response.get("update") or {}).get("state")


def wait_for_update(get_update, timeout_s: int, poll_s: float = 10.0, sleep=time.sleep, now=time.monotonic) -> str:
    """Poll `get_update()` until a terminal state; returns it. Raises TimeoutError."""
    deadline = now() + timeout_s
    while True:
        state = update_state(get_update())
        if state in TERMINAL_OK | TERMINAL_BAD:
            return state
        if now() >= deadline:
            raise TimeoutError(f"pipeline update still {state} after {timeout_s}s")
        sleep(poll_s)


def refresh(client, catalog: str, schema: str, timeout_s: int) -> dict[str, str]:
    """Start and await one pipeline update per existing synced table. Returns {table: outcome}."""
    outcomes: dict[str, str] = {}
    for entity in ENTITIES:
        name = synced_table_name(catalog, schema, entity)
        try:
            resource = client.do("GET", f"/api/2.0/postgres/synced_tables/{name}")
        except Exception as exc:  # noqa: BLE001 - SDK raises NotFound subclasses; message is enough here
            if "does not exist" in str(exc) or "NOT_FOUND" in str(exc) or "TABLE_DOES_NOT_EXIST" in str(exc):
                outcomes[name] = "skipped (not created yet)"
                continue
            raise
        pipeline_id = find_pipeline_id(resource)
        if not pipeline_id:
            raise RuntimeError(f"no pipeline_id found in synced table resource for {name}")
        started = client.do("POST", f"/api/2.0/pipelines/{pipeline_id}/updates", body={})
        update_id = started["update_id"]
        state = wait_for_update(
            lambda: client.do("GET", f"/api/2.0/pipelines/{pipeline_id}/updates/{update_id}"), timeout_s
        )
        outcomes[name] = state
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="classic_stable")
    parser.add_argument("--schema", default="auto_intelligence")
    parser.add_argument("--timeout-s", type=int, default=1800)
    args = parser.parse_args(argv)

    from databricks.sdk import WorkspaceClient  # imported late: unit tests do not need the SDK

    outcomes = refresh(WorkspaceClient().api_client, args.catalog, args.schema, args.timeout_s)
    for table, outcome in outcomes.items():
        print(f"{table}: {outcome}")
    return 1 if any(o in TERMINAL_BAD for o in outcomes.values()) else 0


if __name__ == "__main__":
    # Serverless spark_python_task runs this file via exec() in IPython: ANY sys.exit (even 0) marks the
    # task FAILED, so signal failure by raising and success by simply returning.
    rc = main()
    if rc:
        raise RuntimeError(f"sync failed (rc={rc})")
