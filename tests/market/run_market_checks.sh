#!/usr/bin/env bash
# Market data validation suite (read-only: SELECT queries only; changes nothing in the workspace).
#
# Usage:
#   tests/market/run_market_checks.sh <profile> [target]            run all checks, write evidence/market/
#   tests/market/run_market_checks.sh <profile> [target] snapshot <label>
#                                     write evidence/market/snapshots/<label>.txt (idempotency state)
#   tests/market/run_market_checks.sh <profile> [target] diff <before> <after> [name]
#                                     compare two snapshots, write evidence/market/<name|idempotency>.txt
#
# target: demo (schema auto_intelligence, default) | dev (auto_intelligence_dev).
# Override with MARKET_CATALOG / MARKET_SCHEMA. Allow-lists (comma-separated YYYY-MM-01) must mirror the
# pipeline config: MARKET_KNOWN_MISSING_MONTHS, MARKET_KNOWN_NO_BRAND_TABLE_MONTHS. Exit code 1 if any check fails.
set -uo pipefail

PROFILE="${1:?usage: $0 <profile> [target] [snapshot <label> | diff <before> <after>]}"
TARGET="${2:-demo}"
MODE="${3:-checks}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 2
HERE=tests/market
OUT="${MARKET_EVIDENCE_DIR:-evidence/market}"
mkdir -p "$OUT/checks" "$OUT/snapshots"

CATALOG="${MARKET_CATALOG:-classic_stable}"
case "$TARGET" in
  demo) SCHEMA="${MARKET_SCHEMA:-auto_intelligence}" ;;
  dev)  SCHEMA="${MARKET_SCHEMA:-auto_intelligence_dev}" ;;
  *) echo "unknown target: $TARGET" >&2; exit 2 ;;
esac
T="$CATALOG.$SCHEMA."
VOLUME_DIR="/Volumes/$CATALOG/$SCHEMA/raw_landing/fenabrave"
SHA="$(git rev-parse --short HEAD)"
NOW="$(date -u '+%Y-%m-%d %H:%M UTC')"

redact() { sed -E -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<user>/g' -e "s|$HOME|~|g"; }
KNOWN_MISSING="${MARKET_KNOWN_MISSING_MONTHS-}"          # mirror of pipeline config market.known_missing_months
KNOWN_NO_BRAND="${MARKET_KNOWN_NO_BRAND_TABLE_MONTHS-2004-01-01}"  # mirror of market.known_no_brand_table_months (ADR 99b889d)
KNOWN_NO_MODEL="${MARKET_KNOWN_NO_MODEL_TABLE_MONTHS-2004-01-01}"  # QA rule: p6 checked by hand to have no ranking
OCR_MONTHS="${MARKET_OCR_MONTHS-2020-04,2020-05,2020-06,2023-09,2024-01}"  # no text layer: report-only reconciliation
render() { sed -e "s/__T__/$T/g" -e "s/__KNOWN_MISSING__/$KNOWN_MISSING/g" -e "s/__KNOWN_NO_BRAND__/$KNOWN_NO_BRAND/g" -e "s/__KNOWN_NO_MODEL__/$KNOWN_NO_MODEL/g" "$1"; }
sql() { databricks experimental aitools tools query --profile "$PROFILE" "$@"; }
header() { # claim command result
  printf '# claim:    %s\n# command:  %s\n# target:   %s (%s)\n# git_sha:  %s\n# date:     %s\n# result:   %s\n\n' \
    "$1" "$2" "$TARGET" "${T%.}" "$SHA" "$NOW" "$3"
}

snapshot() { # label
  local f="$OUT/snapshots/$1.txt"
  {
    echo "# snapshot $1 · ${T%.} · $NOW · git $SHA"
    echo "## table_rows"
    for t in market_download_manifest market_raw_documents market_documents market_segment_totals \
             market_registrations_brand market_registrations_model market_synthetic_registrations \
             market_brand_monthly market_model_monthly market_share_real market_share_with_aurora; do
      printf '%s\t%s\n' "$t" "$(sql --output csv "SELECT count(*) FROM $T$t" 2>&1 | tail -n1)"
    done
    echo "## content fingerprints (count, sum of xxhash64 over all columns; bronze excludes the VARIANT payload)"
    for t in market_documents market_segment_totals market_registrations_brand market_registrations_model \
             market_synthetic_registrations market_brand_monthly market_model_monthly market_share_real market_share_with_aurora; do
      printf '%s\t%s\n' "$t" "$(sql --output csv "SELECT concat(count(*), ' ', coalesce(sum(CAST(xxhash64(*) AS DECIMAL(38,0))), 0)) FROM $T$t" 2>&1 | tail -n1)"
    done
    printf '%s\t%s\n' market_raw_documents "$(sql --output csv "SELECT concat(count(*), ' ', coalesce(sum(CAST(xxhash64(source_path, file_size, file_modification_time, _ingested_at) AS DECIMAL(38,0))), 0)) FROM ${T}market_raw_documents" 2>&1 | tail -n1)"
    echo "## manifest (ref_month, status, sha256, downloaded_at)"
    sql --output csv "SELECT source_url, url_month, status, sha256, downloaded_at FROM ${T}market_download_manifest ORDER BY source_url" 2>&1
    echo "## bronze (source_path, file_modification_time, _ingested_at)"
    sql --output csv "SELECT source_path, file_modification_time, _ingested_at FROM ${T}market_raw_documents ORDER BY source_path" 2>&1
    echo "## volume files (path, size, modification_time)"
    databricks fs ls -l --absolute "dbfs:$VOLUME_DIR" --profile "$PROFILE" 2>&1 | sort
    for y in $(databricks fs ls "dbfs:$VOLUME_DIR" --profile "$PROFILE" 2>/dev/null | grep -E '^[0-9]{4}$'); do
      databricks fs ls -l --absolute "dbfs:$VOLUME_DIR/$y" --profile "$PROFILE" 2>&1 | sort
    done
  } | redact > "$f"
  echo "wrote $f"
}

if [[ "$MODE" == "snapshot" ]]; then snapshot "${4:?label}"; exit 0; fi

if [[ "$MODE" == "diff" ]]; then
  a="$OUT/snapshots/${4:?before}.txt"; b="$OUT/snapshots/${5:?after}.txt"; name="${6:-idempotency}"
  d="$(diff <(tail -n +2 "$a") <(tail -n +2 "$b"))"; rc=$?
  {
    case "$name" in
      *pipeline*) claim="a no-change pipeline update re-ingests nothing and leaves every table's rows and contents identical (counts + xxhash64 fingerprints)" ;;
      *) claim="a second job run downloads nothing and adds no rows (snapshots identical apart from the title line)" ;;
    esac
    header "$claim" \
      "diff $a $b" "$([[ $rc -eq 0 ]] && echo PASS || echo FAIL)"
    echo "## before: $(head -n1 "$a")"; echo "## after:  $(head -n1 "$b")"
    echo "## table_rows (before → after)"
    paste <(sed -n '/^## table_rows/,/^## manifest/p' "$a" | sed '1d;$d') \
          <(sed -n '/^## table_rows/,/^## manifest/p' "$b" | sed '1d;$d' | cut -f2) | awk -F'\t' '{print $1": "$2" → "$3}'
    echo; echo "## diff (empty = identical)"; echo "$d"
  } > "$OUT/$name.txt"
  echo "wrote $OUT/$name.txt ($([[ $rc -eq 0 ]] && echo PASS || echo FAIL))"
  exit $(( rc == 0 ? 0 : 1 ))
fi

# --- checks mode -------------------------------------------------------------------------------
fails=0
summary=()
for f in "$HERE"/sql/*.sql; do
  name="$(basename "$f" .sql)"
  claim="$(sed -n 's/^-- claim: //p' "$f" | head -n1)"
  res="$(render "$f" | sql --output csv 2>&1)"; rc=$?
  rows=$(( $(printf '%s\n' "$res" | sed '/^$/d' | wc -l) - 1 ))
  if [[ $rc -ne 0 ]]; then status=ERROR; elif [[ $rows -le 0 ]]; then status=PASS; else status=FAIL; fi
  [[ "$status" == PASS ]] || fails=$((fails + 1))
  {
    header "$claim" "tests/market/sql/$name.sql (violations query: 0 rows = PASS)" "$status"
    echo "## violations: $([[ $rc -eq 0 ]] && echo $(( rows < 0 ? 0 : rows )) || echo 'query error')"
    printf '%s\n' "$res" | head -n 200
    [[ $rows -gt 200 ]] && echo "... truncated ($rows rows)"
    echo; echo "## sql"; render "$f"
  } | redact > "$OUT/checks/$name.txt"
  summary+=("$(printf '%-6s %s' "$status" "$name")")
done

# Reconciliation 1: market_segment_totals vs the independent page-1 oracle (exact).
sql --output csv "SELECT ref_month AS month, segment, units FROM ${T}market_segment_totals ORDER BY 1, 2" \
  > "$OUT/.segment_totals.csv" 2>&1
python3 -I "$HERE/reconcile.py" "$OUT/.segment_totals.csv" "$HERE/oracle" --tolerance-pct 0 --report-only-months "$OCR_MONTHS" > "$OUT/.recon1.txt" 2>&1; r1=$?
# Reconciliation 2: real gold brand rows (incl. residual) vs the oracle (exact).
sql --output csv "SELECT ref_month AS month, segment, sum(units) AS units FROM ${T}market_brand_monthly WHERE NOT is_synthetic GROUP BY 1, 2 ORDER BY 1, 2" \
  > "$OUT/.gold_brand.csv" 2>&1
python3 -I "$HERE/reconcile.py" "$OUT/.gold_brand.csv" "$HERE/oracle" --tolerance-pct 0 --report-only-months "$OCR_MONTHS" > "$OUT/.recon2.txt" 2>&1; r2=$?
# Report only: published brand ranking coverage vs the oracle (top 20/21 for Autos, so a gap is expected).
sql --output csv "SELECT ref_month AS month, segment, sum(units) AS units FROM ${T}market_registrations_brand GROUP BY 1, 2 ORDER BY 1, 2" \
  > "$OUT/.brand_rank.csv" 2>&1
python3 -I "$HERE/reconcile.py" "$OUT/.brand_rank.csv" "$HERE/oracle" --tolerance-pct 3 --report-only --report-only-months "$KNOWN_NO_BRAND" > "$OUT/.recon3.txt" 2>&1
{
  echo "# Reconciliação com os totais impressos nos PDFs"
  echo
  echo "- alvo: \`${T%.}\` ($TARGET) · git \`$SHA\` · $NOW"
  echo "- oráculo: \`tests/market/oracle/pdf_totals.csv\` (página 1, \`pdftotext\`, independente do parser) +"
  echo "  \`pdf_totals_visual_override.csv\` (5 PDFs sem camada de texto, lidos à mão)"
  echo "- resultado: silver totais $([[ $r1 -eq 0 ]] && echo PASS || echo FAIL) · gold marcas $([[ $r2 -eq 0 ]] && echo PASS || echo FAIL) · ranking de marcas (só relatório)"
  for p in "1:market_segment_totals × oráculo (exato):.recon1.txt" "2:market_brand_monthly real, soma com resíduo × oráculo (exato):.recon2.txt" \
           "3:market_registrations_brand (ranking publicado) × oráculo (relatório; tolerância 3%):.recon3.txt"; do
    IFS=: read -r n title file <<<"$p"
    echo; echo "## $n. $title"; echo; echo '```'; cat "$OUT/$file"; echo '```'
  done
} | redact > "$OUT/reconciliation.md"
rm -f "$OUT"/.segment_totals.csv "$OUT"/.gold_brand.csv "$OUT"/.brand_rank.csv "$OUT"/.recon?.txt
[[ $r1 -eq 0 ]] || fails=$((fails + 1)); summary+=("$( [[ $r1 -eq 0 ]] && echo PASS || echo FAIL)   reconciliation_segment_totals")
[[ $r2 -eq 0 ]] || fails=$((fails + 1)); summary+=("$( [[ $r2 -eq 0 ]] && echo PASS || echo FAIL)   reconciliation_gold_brand")

# --- info evidence (D6): not pass/fail on their own; the checks above carry the verdicts ----------
info() { # file claim sql...
  local f="$1" claim="$2"; shift 2
  { header "$claim" "tests/market/run_market_checks.sh (info queries below)" "INFO"
    for q in "$@"; do echo "## $(head -n1 <<<"$q" | sed 's/^-- //')"; sql --output csv "$(tail -n +2 <<<"$q")" 2>&1; echo; done
  } | redact > "$OUT/$f"
}
info coverage.txt "expected months (2003-01..max ref_month) vs present; gaps vs market.known_missing_months [$KNOWN_MISSING]; no-brand-table months [$KNOWN_NO_BRAND]" \
  "-- window and counts
WITH e AS (SELECT explode(sequence(DATE'2003-01-01', (SELECT max(ref_month) FROM ${T}market_segment_totals), INTERVAL 1 MONTH)) AS ref_month)
SELECT min(e.ref_month) AS first_expected, max(e.ref_month) AS last_expected, count(*) AS expected_months,
       count(t.ref_month) AS present_months, count(*) - count(t.ref_month) AS absent_months
FROM e LEFT JOIN (SELECT DISTINCT ref_month FROM ${T}market_segment_totals) t USING (ref_month)" \
  "-- absent months (must be empty or allow-listed)
WITH e AS (SELECT explode(sequence(DATE'2003-01-01', (SELECT max(ref_month) FROM ${T}market_segment_totals), INTERVAL 1 MONTH)) AS ref_month)
SELECT ref_month FROM e LEFT ANTI JOIN ${T}market_segment_totals USING (ref_month) ORDER BY 1" \
  "-- months without brand or model table
SELECT ref_month, segment, brand_table_found, model_table_found, source_file FROM ${T}market_segment_totals
WHERE NOT brand_table_found OR NOT model_table_found ORDER BY 1, 2" \
  "-- months resolved from more than one file (latest source_last_modified wins)
SELECT ref_month, count(*) AS n_files, collect_list(concat(file_name, CASE WHEN is_selected THEN ' (selected)' ELSE '' END)) AS files
FROM ${T}market_documents WHERE ref_month IS NOT NULL GROUP BY ref_month HAVING count(*) > 1 ORDER BY 1" \
  "-- documents whose month differs from the URL/file name month
SELECT file_name, ref_month, month_source FROM ${T}market_documents
WHERE ref_month IS NOT NULL AND regexp_extract(file_name, '(\\\\d{4})_(\\\\d{2})', 0) <> date_format(ref_month, 'yyyy_MM') ORDER BY 2" \
  "-- documents not parsed ok (month_resolved warn; never selected)
SELECT file_name, parse_status, ref_month, is_selected, parse_dialect FROM ${T}market_documents
WHERE parse_status <> 'ok' OR ref_month IS NULL ORDER BY file_name" \
  "-- month_source and parse_status distribution
SELECT month_source, parse_status, parse_dialect, count(*) AS n FROM ${T}market_documents GROUP BY ALL ORDER BY ALL"
info manifest.txt "download manifest by status x origin; candidate URLs without a file" \
  "-- status x origin
SELECT status, origin, count(*) AS n, count(DISTINCT url_month) AS url_months FROM ${T}market_download_manifest GROUP BY ALL ORDER BY ALL" \
  "-- url months with no downloaded file
SELECT url_month, collect_list(concat(status, ' ', coalesce(CAST(http_status AS STRING), '-'))) AS attempts
FROM ${T}market_download_manifest GROUP BY url_month HAVING count_if(status = 'downloaded') = 0 ORDER BY 1" \
  "-- duplicates (same content, other URL)
SELECT source_url, duplicate_of FROM ${T}market_download_manifest WHERE status = 'duplicate' ORDER BY 1"
info synthetic-isolation.txt "synthetic rows only in Aurora tables/rows; real totals unchanged with and without Aurora" \
  "-- rows by is_synthetic in gold and views
SELECT 'market_brand_monthly' AS tbl, is_synthetic, count(*) AS n_rows, sum(units) AS units FROM ${T}market_brand_monthly GROUP BY ALL
UNION ALL SELECT 'market_model_monthly', is_synthetic, count(*), sum(units) FROM ${T}market_model_monthly GROUP BY ALL
UNION ALL SELECT 'market_share_real', is_synthetic, count(*), sum(units) FROM ${T}market_share_real GROUP BY ALL
UNION ALL SELECT 'market_share_with_aurora', is_synthetic, count(*), sum(units) FROM ${T}market_share_with_aurora GROUP BY ALL
ORDER BY 1, 2" \
  "-- Aurora brand name in real silver tables (must be 0)
SELECT (SELECT count(*) FROM ${T}market_registrations_brand WHERE upper(brand) LIKE '%AURORA%') AS in_brand_silver,
       (SELECT count(*) FROM ${T}market_registrations_model WHERE upper(brand) LIKE '%AURORA%') AS in_model_silver,
       (SELECT count(*) FROM ${T}market_share_real WHERE upper(brand) LIKE '%AURORA%' OR is_synthetic) AS in_real_view" \
  "-- automoveis per year: published total, real view, with-Aurora view, Aurora share (Dec)
SELECT year(t.ref_month) AS yr, sum(t.units) AS published, sum(r.u) AS real_view, sum(w.u) AS with_aurora,
       sum(w.u) - sum(t.units) AS aurora_units, round(100 * (sum(w.u) - sum(t.units)) / sum(w.u), 2) AS aurora_share_pct
FROM ${T}market_segment_totals t
JOIN (SELECT ref_month, segment, sum(units) u FROM ${T}market_share_real GROUP BY ALL) r USING (ref_month, segment)
JOIN (SELECT ref_month, segment, sum(units) u FROM ${T}market_share_with_aurora GROUP BY ALL) w USING (ref_month, segment)
WHERE t.segment = 'automoveis' GROUP BY 1 ORDER BY 1"
info quality.txt "parser quality: unmatched brands in the model ranking, ranking coverage of the published total" \
  "-- unmatched brand_raw values (brand_matched = false)
SELECT brand_raw, brand, count(*) AS n_rows, count(DISTINCT ref_month) AS n_months, min(ref_month) AS first_month, max(ref_month) AS last_month
FROM ${T}market_registrations_model WHERE NOT brand_matched GROUP BY ALL ORDER BY n_rows DESC" \
  "-- brand series that start or end inside the window (renames are not unified, R8; known: 2023-06/07 CL rename)
SELECT segment, brand, min(ref_month) AS first_month, max(ref_month) AS last_month, count(*) AS n_months
FROM ${T}market_registrations_brand GROUP BY ALL
HAVING min(ref_month) > DATE'2003-01-01' OR max(ref_month) < (SELECT max(ref_month) FROM ${T}market_segment_totals)
ORDER BY segment, first_month" \
  "-- models whose name starts with the brand (source literal, e.g. X/X/MODEL; review only)
SELECT ref_month, segment, brand, model, units FROM ${T}market_registrations_model WHERE model LIKE concat(brand, '/%') ORDER BY 1" \
  "-- residual share by segment (min / avg / max) and worst months
SELECT segment, round(100 * min(r), 3) AS min_pct, round(100 * avg(r), 3) AS avg_pct, round(100 * max(r), 3) AS max_pct
FROM (SELECT b.ref_month, b.segment, b.units / t.units AS r FROM ${T}market_brand_monthly b
      JOIN ${T}market_segment_totals t USING (ref_month, segment) WHERE b.is_residual AND t.brand_table_found) GROUP BY 1" \
  "-- model ranking coverage of the published total (top 50; report only)
SELECT m.segment, round(100 * min(m.u / t.units), 2) AS min_pct, round(100 * avg(m.u / t.units), 2) AS avg_pct, round(100 * max(m.u / t.units), 2) AS max_pct
FROM (SELECT ref_month, segment, sum(units) u FROM ${T}market_registrations_model GROUP BY ALL) m
JOIN ${T}market_segment_totals t USING (ref_month, segment) GROUP BY 1"

# Row counts per month x segment (evidence, not a check).
{
  header "rows per month and segment in silver and gold" "SELECT ... GROUP BY ref_month, segment" "INFO"
  sql --output csv "SELECT 'totals' AS tbl, ref_month, segment, 1 AS n_rows, units FROM ${T}market_segment_totals
    UNION ALL SELECT 'brand', ref_month, segment, count(*), sum(units) FROM ${T}market_registrations_brand GROUP BY ALL
    UNION ALL SELECT 'model', ref_month, segment, count(*), sum(units) FROM ${T}market_registrations_model GROUP BY ALL
    UNION ALL SELECT 'synthetic', ref_month, segment, count(*), sum(units) FROM ${T}market_synthetic_registrations GROUP BY ALL
    ORDER BY ref_month, segment, tbl" 2>&1
} | redact > "$OUT/row-counts.txt"

# Mask real brand names in every evidence file written above (ADR D6; reproducible on re-run).
sql --output csv "SELECT brand FROM ${T}market_registrations_brand UNION SELECT brand FROM ${T}market_registrations_model
  UNION SELECT brand_raw FROM ${T}market_registrations_model UNION SELECT brand FROM ${T}market_brand_monthly" \
  > "$OUT/.brands.txt" 2>&1
if python3 -I "$HERE/mask_brands.py" "$OUT/.brands.txt" "$OUT"/checks/*.txt "$OUT"/*.md "$OUT"/coverage.txt "$OUT"/manifest.txt \
     "$OUT"/synthetic-isolation.txt "$OUT"/quality.txt "$OUT"/row-counts.txt; then
  summary+=("PASS   brand_masking")
else
  fails=$((fails + 1)); summary+=("FAIL   brand_masking")
fi
rm -f "$OUT/.brands.txt"

{
  header "market validation suite: all checks" "tests/market/run_market_checks.sh $PROFILE $TARGET" \
    "$([[ $fails -eq 0 ]] && echo PASS || echo "FAIL ($fails)")"
  printf '%s\n' "${summary[@]}"
} | tee "$OUT/summary.txt"
exit $(( fails == 0 ? 0 : 1 ))
