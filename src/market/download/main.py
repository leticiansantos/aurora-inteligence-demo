"""Entry point of the `download` task (spark_python_task, serverless).

Args: --catalog <catalog> --schema <schema>
Discovers Fenabrave PDFs (seed history + new months), lands them unchanged in
/Volumes/<catalog>/<schema>/raw_landing/fenabrave/<url_year>/<basename>, records one manifest row per
candidate URL (MERGE on source_url) and publishes the task value `new_files`.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime

# The task file is synced by the bundle; make sibling modules importable regardless of how it is launched.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
except NameError:  # __file__ undefined (e.g. exec'd source)
    sys.path.insert(0, os.getcwd())

from fetch import finalize, probe_all  # noqa: E402
from planning import build_candidates, load_seed, select_to_probe  # noqa: E402

MANIFEST_DDL_COLUMNS = """
    source_url STRING, url_month DATE, file_path STRING, bytes BIGINT, sha256 STRING, status STRING,
    duplicate_of STRING, http_status INT, origin STRING, source_last_modified TIMESTAMP,
    attempted_at TIMESTAMP, downloaded_at TIMESTAMP
"""


def load_manifest_state(spark, table: str) -> tuple[dict[str, str], dict[str, str]]:
    """(source_url -> status, sha256 -> source_url of landed files) from the existing manifest."""
    spark.sql(f"CREATE TABLE IF NOT EXISTS {table} ({MANIFEST_DDL_COLUMNS}) "
              "COMMENT 'Fenabrave download manifest: one row per candidate URL (written by the market_monthly job).'")
    rows = spark.sql(f"SELECT source_url, status, sha256 FROM {table}").collect()
    statuses = {r.source_url: r.status for r in rows}
    hashes = {r.sha256: r.source_url for r in rows if r.status == "downloaded" and r.sha256}
    return statuses, hashes


def merge_rows(spark, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    df = spark.createDataFrame(rows, schema=MANIFEST_DDL_COLUMNS.replace("\n", " ").strip())
    df.createOrReplaceTempView("_market_manifest_updates")
    spark.sql(f"""
        MERGE INTO {table} t USING _market_manifest_updates s ON t.source_url = s.source_url
        WHEN MATCHED THEN UPDATE SET
          t.url_month = s.url_month, t.http_status = s.http_status, t.attempted_at = s.attempted_at,
          t.source_last_modified = coalesce(s.source_last_modified, t.source_last_modified),
          t.status = s.status, t.file_path = coalesce(s.file_path, t.file_path), t.bytes = coalesce(s.bytes, t.bytes),
          t.sha256 = coalesce(s.sha256, t.sha256), t.duplicate_of = s.duplicate_of,
          t.downloaded_at = coalesce(t.downloaded_at, s.downloaded_at)
        WHEN NOT MATCHED THEN INSERT *
    """)


def set_task_value(n: int) -> None:
    try:
        from databricks.sdk.runtime import dbutils
    except ImportError as e:  # local runs only: no Databricks runtime
        print(f"[warn] no dbutils available, task value new_files={n} not set: {e}")
        return
    dbutils.jobs.taskValues.set("new_files", n)  # on a job run, failures must surface here


def run(spark, catalog: str, schema: str, today: date | None = None) -> int:
    today = today or date.today()
    table = f"{catalog}.{schema}.market_download_manifest"
    root = f"/Volumes/{catalog}/{schema}/raw_landing"
    landing, tmp = f"{root}/fenabrave", f"{root}/_tmp_fenabrave"
    statuses, hashes = load_manifest_state(spark, table)
    todo = select_to_probe(build_candidates(load_seed(), today), statuses, today)
    print(f"candidates to probe: {len(todo)} (manifest rows: {len(statuses)})")
    probes = probe_all(todo, tmp)
    rows = finalize(probes, hashes, landing, datetime.utcnow())
    conflicts = [(r["source_url"], r.pop("conflict")) for r in rows if "conflict" in r]
    merge_rows(spark, table, rows)
    for url, msg in conflicts:
        print(f"[conflict] {url} {msg}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"run summary: {counts}")
    for r in rows:
        if r["status"] == "failed":
            print(f"[failed] {r['source_url']} http={r['http_status']}")
    return counts.get("downloaded", 0)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    args = ap.parse_args(argv)
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    n = run(spark, args.catalog, args.schema)
    print(f"new_files={n}")
    set_task_value(n)


if __name__ == "__main__":
    main()
