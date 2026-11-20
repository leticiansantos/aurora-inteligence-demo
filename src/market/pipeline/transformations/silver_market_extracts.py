"""Silver: segment totals, brand ranking and model ranking per month (ADR D2/D3, section 4)."""
from pyspark import pipelines as dp
from pyspark.sql import functions as F

SEGMENTS = "segment IN ('automoveis', 'comerciais_leves')"
KNOWN_NO_BRAND_TABLE = [m.strip() for m in spark.conf.get("market.known_no_brand_table_months", "").split(",") if m.strip()]
NO_BRAND_LIST = ", ".join(f"'{m}'" for m in KNOWN_NO_BRAND_TABLE) or "''"
KNOWN_NO_MODEL_TABLE = [m.strip() for m in spark.conf.get("market.known_no_model_table_months", "").split(",") if m.strip()]
NO_MODEL_LIST = ", ".join(f"'{m}'" for m in KNOWN_NO_MODEL_TABLE) or "''"


def _selected():
    return spark.read.table("market_parsed_documents").where("is_selected AND ref_month IS NOT NULL")


@dp.materialized_view(name="market_segment_totals", comment="Published monthly totals per segment (share denominator)")
@dp.expect_or_fail("segment_valid", SEGMENTS)
@dp.expect_or_fail("units_non_negative", "units >= 0")
@dp.expect("brand_table_found_or_known", f"brand_table_found OR date_format(ref_month, 'yyyy-MM') IN ({NO_BRAND_LIST})")
@dp.expect("model_table_found_or_known", f"model_table_found OR date_format(ref_month, 'yyyy-MM') IN ({NO_MODEL_LIST})")
def market_segment_totals():
    d = _selected().select("ref_month", F.explode("totals").alias("t"), "brand_segments", "model_segments",
                           F.col("file_name").alias("source_file"), "parse_dialect")
    return d.select(
        "ref_month", F.col("t.segment").alias("segment"), F.col("t.units").alias("units"),
        F.array_contains("brand_segments", F.col("t.segment")).alias("brand_table_found"),
        F.array_contains("model_segments", F.col("t.segment")).alias("model_table_found"),
        "source_file", "parse_dialect")


@dp.materialized_view(name="market_registrations_brand", comment="Real brand ranking per month and segment (top 20/21)")
@dp.expect_or_fail("segment_valid", SEGMENTS)
@dp.expect_or_fail("units_non_negative", "units >= 0")
@dp.expect("rank_positive", "rank >= 1")
def market_registrations_brand():
    d = _selected().select("ref_month", F.explode("brands").alias("b"),
                           F.col("file_name").alias("source_file"), "parse_dialect")
    return (d.select("ref_month", "b.*", "source_file", "parse_dialect")
             .groupBy("ref_month", "segment", "brand")
             .agg(F.sum("units").cast("int").alias("units"), F.min("rank").alias("rank"),
                  F.first("source_file").alias("source_file"), F.min("page_id").alias("page_id"),
                  F.first("parse_dialect").alias("parse_dialect"))
             .select("ref_month", "segment", "brand", "units", "rank", "source_file", "page_id", "parse_dialect"))


@dp.materialized_view(name="market_registrations_model", comment="Real model ranking per month and segment (top 50)")
@dp.expect_or_fail("segment_valid", SEGMENTS)
@dp.expect_or_fail("units_non_negative", "units >= 0")
@dp.expect("rank_positive", "rank >= 1")
@dp.expect("brand_matched", "brand_matched")
def market_registrations_model():
    d = _selected().select("ref_month", F.explode("models").alias("m"),
                           F.col("file_name").alias("source_file"), "parse_dialect")
    return (d.select("ref_month", "m.*", "source_file", "parse_dialect")
             .groupBy("ref_month", "segment", "brand", "model")
             .agg(F.first("brand_raw").alias("brand_raw"), F.max("brand_matched").alias("brand_matched"),
                  F.sum("units").cast("int").alias("units"), F.min("rank").alias("rank"),
                  F.first("source_file").alias("source_file"), F.min("page_id").alias("page_id"),
                  F.first("parse_dialect").alias("parse_dialect"))
             .select("ref_month", "segment", "brand", "brand_raw", "brand_matched", "model", "units", "rank",
                     "source_file", "page_id", "parse_dialect"))


@dp.materialized_view(name="market_rank_checks",
                      comment="Rank sanity per month, segment and ranking (rank 1 present, ranks in order)")
@dp.expect("rank_sequence_ok", "min_rank = 1 AND ranks_in_order")
def market_rank_checks():
    d = _selected().select("ref_month", "brands", "models", "brand_segments", "model_segments")
    out = None
    for seg in ("automoveis", "comerciais_leves"):
        for kind in ("brands", "models"):
            rows = F.filter(F.col(kind), lambda r: r["segment"] == seg)
            part = (d.where(F.size(rows) > 0)
                     .select("ref_month", F.lit(seg).alias("segment"), F.lit(kind).alias("ranking"),
                             F.size(rows).alias("row_count"),
                             # ties are legal (top 20/21): rank 1 must exist and ranks must not decrease
                             F.array_min(F.transform(rows, lambda r: r["rank"])).alias("min_rank"),
                             (F.transform(rows, lambda r: r["rank"])
                              == F.array_sort(F.transform(rows, lambda r: r["rank"]))).alias("ranks_in_order")))
            out = part if out is None else out.unionByName(part)
    return out
