-- claim: exactly one file is selected per month, every selected file parsed ok with a month, unresolved files are
--        never selected, and the selected file is the source of that month's totals (gaps are caught by 01)
-- returns: offending documents or months
SELECT 'selected_not_parsed_ok' AS violation, file_name AS key, CAST(ref_month AS STRING) AS ref_month, parse_status AS detail
FROM __T__market_documents
WHERE is_selected IS NULL OR parse_status IS NULL
   OR (is_selected AND (parse_status <> 'ok' OR ref_month IS NULL))
UNION ALL
SELECT 'selected_count_ne_1', CAST(ref_month AS STRING), CAST(ref_month AS STRING), CAST(count_if(is_selected) AS STRING)
FROM __T__market_documents WHERE ref_month IS NOT NULL
GROUP BY ref_month HAVING count_if(is_selected) <> 1
UNION ALL
SELECT 'totals_not_from_selected_file', t.source_file, CAST(t.ref_month AS STRING), t.segment
FROM __T__market_segment_totals t
LEFT ANTI JOIN __T__market_documents d
  ON d.ref_month = t.ref_month AND d.is_selected AND (d.file_name = t.source_file OR d.source_path = t.source_file)
UNION ALL
SELECT 'bad_month_source', file_name, CAST(ref_month AS STRING), month_source
FROM __T__market_documents
WHERE parse_status = 'ok' AND (month_source IS NULL OR month_source NOT IN ('p6_header', 'p1_header', 'title'))
