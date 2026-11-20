-- Bronze: one row per PDF, parsed once with ai_parse_document (pages 1, 6 and 8 only).
-- Streaming table => each file is parsed a single time; reset is blocked so an accidental
-- full refresh cannot re-bill every parse (ADR D2).
CREATE OR REFRESH STREAMING TABLE market_raw_documents
COMMENT 'Fenabrave monthly PDFs, parsed once with ai_parse_document (pageRange 1,6,8)'
TBLPROPERTIES ('pipelines.reset.allowed' = 'false')
AS SELECT
  path AS source_path,
  regexp_extract(path, '[^/]+$', 0) AS file_name,
  length AS file_size,
  modificationTime AS file_modification_time,
  ai_parse_document(content, map('version', '2.0', 'descriptionElementTypes', '', 'pageRange', '1,6,8')) AS parsed,
  current_timestamp() AS _ingested_at
FROM STREAM read_files(
  '${market.landing_path}',
  format => 'binaryFile',
  pathGlobFilter => '*.pdf',
  allowOverwrites => 'false'
);
