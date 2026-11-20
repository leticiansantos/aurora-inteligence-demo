# Market API adversarial probes (beyond api-vs-sql.txt)
# server: team/mkv1-backend @f1b603f, local :8903; 2026-11-20 15:54 UTC

```
## cache: same query twice (month=2015-05 never requested before)
cached= False generatedAt= 2026-11-20T15:50:05.636Z realUnits= 175636 yoy= -0.2449757762560022
time=2.538954s
cached= True generatedAt= 2026-11-20T15:50:05.636Z realUnits= 175636 yoy= -0.2449757762560022
time=0.001210s
## cache key: limit 3 vs limit 5 on same month/segment/view
limit rows(non-res)= 3 othersUnits= 98143 cached= False
limit rows(non-res)= 5 othersUnits= 59981 cached= True
## month YYYY-MM vs YYYY-MM-01 give identical payload (minus meta)
PASS identical
## concurrency: 10 parallel cold requests (distinct months)
2010-01 200 0.989702s
2010-10 200 1.601004s
2010-09 200 1.617954s
2010-04 200 2.005168s
2010-07 200 2.232070s
2010-02 200 2.305989s
2010-06 200 2.319926s
2010-05 200 2.613054s
2010-03 200 2.690524s
2010-08 200 2.846105s
## warehouse id bogus (0000000000000000) -> expect 503 warehouse_unavailable, no leak
{"error":{"code":"warehouse_unavailable","message":"warehouse query failed"}}  [503]
{"error":{"code":"warehouse_unavailable","message":"warehouse query failed"}}  [503]
{"error":{"code":"warehouse_unavailable","message":"warehouse query failed"}}  [503]
{"error":{"code":"warehouse_unavailable","message":"warehouse query failed"}}  [503]
## schema bogus is a separate restart; skipped
```

## backend unit tests / typecheck / lint (checkout @f1b603f)
```
 Test Files  2 passed (2)
      Tests  34 passed (34)
tsc exit 0
eslint done
```

## code review notes (verified by reading the cited lines)
- cache.ts:19: at 500 entries the cache clear()s everything, coverage and in-flight loads included (LOW-MED)
- routes.ts:53-55: any error that is not a ParamError/DataShapeError becomes 503 warehouse_unavailable, code bugs included (LOW)
- SQL: every user param is enum- or regex-checked and bound as a :marker; only the validated catalog/schema identifiers are interpolated (server.ts:11-17)
- Unknown /api/market/<x> -> Express HTML 404 (intended per backend)

## Re-verification of T6 fixes (team/mkv1-backend @eb93a60, 2026-11-20 16:00 UTC)

- api-vs-sql.txt re-run on eb93a60: 1411 checks, 0 FAIL
- unit tests 37/37, tsc 0, eslint 0
- 500 path for non-warehouse errors: covered by unit tests market.test.ts:202 (code bug) and :212 (bad data); a code bug can't be triggered live without editing product code

```
## eviction walk: 285 distinct months x brands period=all (=~570 keys > 500), then re-request coverage-backed summary
 285 200
cached= True total= 49893750 [200 0.001153s]
cached= True total= 49893750 [200 0.000927s]
server RSS MB: 581
## after the walk: mid-range keys must survive (old clear() at 500 keeps only the ~35 newest months)
2003-02 cached= False
2008-06 cached= True
2010-06 cached= True
2015-01 cached= True
2020-01 cached= True
## eb93a60, bogus warehouse id -> 503 warehouse_unavailable
{"error":{"code":"warehouse_unavailable","message":"warehouse query failed"}}  [503]
{"error":{"code":"warehouse_unavailable","message":"warehouse query failed"}}  [503]
{"error":{"code":"warehouse_unavailable","message":"warehouse query failed"}}  [503]
{"error":{"code":"warehouse_unavailable","message":"warehouse query failed"}}  [503]
```
Result: about 570 keys went in and only the oldest were evicted (2003-02 cold; 2008-06..2020-01 still cached). The old clear() would have kept only the ~35 newest months. Fix (1) is verified. The 503 path still works and leaks nothing.
