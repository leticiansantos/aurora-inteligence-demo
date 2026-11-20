"""Job task `generate`: writes the synthetic aftersales landing files (deterministic, overwrite).

Reads the Aurora registrations from Tela 1 (market_synthetic_registrations) with Spark and hands plain data to the
pure generator. Usage: main.py --catalog C --schema S [--out-dir /Volumes/C/S/raw_landing/aftersales]
"""
import argparse
import os
import sys

# The task file is synced by the bundle; serverless may exec the source without __file__.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
except NameError:  # __file__ undefined (exec'd source): the task cwd is the synced folder
    sys.path.insert(0, os.getcwd())

from aftersales_config import DEFAULT_CONFIG  # noqa: E402
from aftersales_generator import fleet_by_dealer_month  # noqa: E402
from aftersales_writer import write_all  # noqa: E402


def load_registrations(spark, catalog: str, schema: str) -> dict:
    rows = spark.table(f"{catalog}.{schema}.market_synthetic_registrations").select(
        "ref_month", "model", "units").collect()
    return {(r["ref_month"], r["model"]): float(r["units"]) for r in rows}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--out-dir", default=None)
    args, _ = ap.parse_known_args(argv)
    out_dir = args.out_dir or f"/Volumes/{args.catalog}/{args.schema}/raw_landing/aftersales"
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    regs = load_registrations(spark, args.catalog, args.schema)
    if not regs:
        raise RuntimeError("market_synthetic_registrations is empty; run the market pipeline first")
    counts = write_all(out_dir, fleet_by_dealer_month(regs, DEFAULT_CONFIG), DEFAULT_CONFIG)
    print(f"[aftersales_generate] {DEFAULT_CONFIG.version} seed={DEFAULT_CONFIG.seed} -> {out_dir}: {counts}")


if __name__ == "__main__":
    main()
