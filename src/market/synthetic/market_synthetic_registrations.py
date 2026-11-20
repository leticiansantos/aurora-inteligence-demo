"""SDP materialized view: synthetic Aurora Motors registrations (ADR D4).

Lazy by design (no .collect()/.count() inside the dataset function): the share/weight curve is
precomputed in Python from the versioned config, then joined with `market_segment_totals` and the
volumes are computed with Spark expressions (the same math as `generate_rows`, the unit-test oracle).
"""
import os
import sys

# The pipeline loads this file from a glob; make sibling modules importable.
_here = None
try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:  # __file__ missing when executed as a notebook-style source
    _here = os.path.join(os.getcwd(), "src", "market", "synthetic")
if _here not in sys.path:
    sys.path.insert(0, _here)

from pyspark import pipelines as dp  # noqa: E402
from pyspark.sql import Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402
from pyspark.sql.types import (  # noqa: E402
    BooleanType, DateType, DoubleType, IntegerType, StringType, StructField, StructType,
)

try:
    from aurora_config import DEFAULT_CONFIG
    from aurora_generator import curve_rows
except ImportError:
    print(f"[market_synthetic] cannot import siblings; __file__ dir={_here}; sys.path={sys.path}")
    raise

CURVE_SCHEMA = StructType([
    StructField("ref_month", DateType()), StructField("model", StringType()), StructField("tie_idx", IntegerType()),
    StructField("target_share", DoubleType()), StructField("weight", DoubleType()),
])


@dp.materialized_view(name="market_synthetic_registrations", comment="Fictional Aurora Motors registrations (synthetic)")
def market_synthetic_registrations():
    cfg = DEFAULT_CONFIG
    curve = spark.createDataFrame(curve_rows(cfg), schema=CURVE_SCHEMA)  # noqa: F821  (local list, no action)
    totals = (
        spark.read.table("market_segment_totals")  # noqa: F821
        .where((F.col("segment") == cfg.segment) & (F.col("ref_month") >= F.lit(cfg.launch_date))
               & F.col("units").isNotNull() & (F.col("units") >= 0))
        .select("ref_month", F.col("units").alias("total_real"))
    )
    j = totals.join(curve, "ref_month")  # months before launch / beyond the curve produce no rows
    # F.rint = round-half-even, same as Python round() in generate_rows
    j = j.withColumn("aurora_total", F.rint(F.col("target_share") * F.col("total_real") / (1 - F.col("target_share"))).cast("long"))
    j = j.withColumn("raw", F.col("aurora_total") * F.col("weight"))
    j = j.withColumn("base", F.floor("raw")).withColumn("frac", F.col("raw") - F.col("base"))
    w_rank = Window.partitionBy("ref_month").orderBy(F.col("frac").desc(), F.col("tie_idx").asc())
    w_sum = Window.partitionBy("ref_month")
    j = j.withColumn("rn", F.row_number().over(w_rank)).withColumn("remainder", F.col("aurora_total") - F.sum("base").over(w_sum))
    return j.select(
        "ref_month",
        F.lit(cfg.segment).alias("segment"),
        F.lit(cfg.brand).alias("brand"),
        "model",
        (F.col("base") + F.when(F.col("rn") <= F.col("remainder"), 1).otherwise(0)).cast("int").alias("units"),
        "target_share",
        F.lit(True).alias("is_synthetic"),
        F.lit(cfg.version).alias("generator_version"),
        F.lit(cfg.seed).cast("int").alias("seed"),
    )
