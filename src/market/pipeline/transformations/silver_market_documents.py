"""Silver: one row per PDF with the resolved reference month (ADR D2).

`market_parsed_documents` (helper MV) runs the pure-Python parser once per file and keeps the extracted
arrays; `market_documents` is its public projection; the extraction tables live in
silver_market_extracts.py.
"""
import sys

from pyspark import pipelines as dp
from pyspark.sql import Window, functions as F, types as T

from utilities import market_parse

# The UDF must ship the parser by value: the module is not installed on the executors.
try:
    from pyspark import cloudpickle
except ImportError:  # pragma: no cover
    import cloudpickle
cloudpickle.register_pickle_by_value(market_parse)

SEGMENT_TOTAL = T.StructType([T.StructField("segment", T.StringType()), T.StructField("units", T.IntegerType())])
BRAND_ROW = T.StructType([
    T.StructField("segment", T.StringType()), T.StructField("brand", T.StringType()),
    T.StructField("units", T.IntegerType()), T.StructField("rank", T.IntegerType()),
    T.StructField("page_id", T.IntegerType())])
MODEL_ROW = T.StructType([
    T.StructField("segment", T.StringType()), T.StructField("brand", T.StringType()),
    T.StructField("brand_raw", T.StringType()), T.StructField("brand_matched", T.BooleanType()),
    T.StructField("model", T.StringType()), T.StructField("units", T.IntegerType()),
    T.StructField("rank", T.IntegerType()), T.StructField("page_id", T.IntegerType())])
PARSED = T.StructType([
    T.StructField("ref_month", T.StringType()), T.StructField("month_source", T.StringType()),
    T.StructField("month_conflict", T.BooleanType()), T.StructField("parse_dialect", T.StringType()),
    T.StructField("parse_status", T.StringType()),
    T.StructField("totals", T.ArrayType(SEGMENT_TOTAL)), T.StructField("brands", T.ArrayType(BRAND_ROW)),
    T.StructField("models", T.ArrayType(MODEL_ROW)),
    T.StructField("brand_segments", T.ArrayType(T.StringType())),
    T.StructField("model_segments", T.ArrayType(T.StringType()))])


# No function is defined in this file for executor use: a function defined here would be pickled by
# reference to the SDP runtime module, which does not exist on the executors. market_parse is
# registered above to be pickled by value, so its function object ships with its code (stdlib only).
parse_elements = F.udf(market_parse.parse_document_json, PARSED)


@dp.materialized_view(name="market_parsed_documents",
                      comment="Parser output per PDF (arrays); feeds the silver tables")
@dp.expect("one_file_per_month", "ref_month IS NULL OR files_in_month = 1")
@dp.expect("month_sources_agree", "NOT month_conflict")
def market_parsed_documents():
    raw = spark.read.table("market_raw_documents").select(
        "source_path", "file_name", "file_modification_time", "_ingested_at",
        F.expr("to_json(parsed:document:elements)").alias("elements_json"))
    parsed = raw.withColumn("p", parse_elements("elements_json")).drop("elements_json")
    # 'no elements' (parse error) is distinguishable from 'no month' by the parser itself
    d = (parsed.select("source_path", "file_name", "file_modification_time", "_ingested_at", "p.*")
         .withColumn("ref_month", F.to_date("ref_month")))
    d = d.withColumn("source_last_modified", F.col("file_modification_time"))  # file mtime; no manifest read
    w = Window.partitionBy("ref_month")
    ranked = Window.partitionBy("ref_month").orderBy(F.col("source_last_modified").desc(), F.col("source_path").desc())
    return (d.withColumn("files_in_month", F.count("*").over(w))
             .withColumn("_rn", F.row_number().over(ranked))
             # an unreadable PDF (no month) is never selected, so it cannot block later updates
             .withColumn("is_selected", F.col("ref_month").isNotNull() & (F.col("_rn") == 1))
             .drop("_rn"))


@dp.materialized_view(name="market_documents", comment="One row per PDF: reference month, dialect and selection")
@dp.expect("month_resolved", "ref_month IS NOT NULL")  # warn: gaps surface in the coverage check
def market_documents():
    return spark.read.table("market_parsed_documents").select(
        "source_path", "file_name", "ref_month", "month_source", "parse_dialect", "parse_status",
        "is_selected", "source_last_modified", "_ingested_at")
