# Market screen QA (`/mercado`, `/api/market/*`)

Adversarial checks of the Market API and screen against the gold tables. The rules for the data are in
[`docs/data-model/market.md`](../../docs/data-model/market.md) and the API contract is in
[`app/shared/market.ts`](../../app/shared/market.ts). The evidence these checks produce goes to
`evidence/app-market/` as text.

## Files

| File | What it does |
|---|---|
| `sql/01_summary.sql` | Oracle for the KPIs of one month: real total, Aurora, YoY, Aurora share and rank |
| `sql/02_timeseries.sql` | Oracle for the monthly series between `:from` and `:to` |
| `sql/03_brands.sql` | Oracle for the full brand list over a month range, with `dense_rank` and `row_number` |
| `sql/04_models.sql` | Oracle for every published model of a month: `row_number`, share, covered units |
| `check_api.py` | Calls the API and the SQL, compares the two and writes `evidence/app-market/api-vs-sql.txt` |

The oracles read `market_segment_totals`, `market_brand_monthly` and `market_model_monthly` directly. They
never read the `market_share_*` tables, so a bug in those tables, or in a server that reads them, shows up as
a difference.

```bash
# server running locally on :8903 (see the run brief for env vars)
python3 -I tests/app-market/check_api.py --base http://localhost:8903 \
  --profile classic-stable-new --warehouse 754bcdfc4beaaaa1
# mask check: no real brand left in the evidence
python3 -I tests/market/mask_brands.py <brands.txt> evidence/app-market/api-vs-sql.txt
```

## Checklist

API (`check_api.py`, months latest / 2023-03 / 2007-06 / 2004-01 × 3 segments × 2 views):

- [ ] summary: realUnits, auroraUnits, totalUnits, previousYearUnits, yoyPct, Aurora share, rank and
      rankedBrands, previousYearShare and shareChangePp all match SQL
- [ ] `aurora` is null for view real, for comerciais_leves and before 2019-01. It is not 0.
- [ ] Switching the view never changes `realUnits`, in summary or in any timeseries point
- [ ] timeseries: from/to and the point count per period (12, 24, 60, all = 285) match, every point matches,
      no Aurora before 2019-01 or in comerciais_leves
- [ ] brands, for the month and for the 24-month window: each row's units, share and dense rank match; the
      rows are sorted; the residual comes last with no rank and the label "Outras (não publicadas)";
      `othersUnits` equals the cut brands; units add up to the total and shares add up to 1
- [ ] brands 2004-01 (prévia): the list holds only the residual, at 100%
- [ ] models: row_number order, share uses the combined total, `coveredUnits` is below `totalUnits`; 2004-01
      falls back to 2003-12 with `month` != `latestMonth`; no Aurora model in view real
- [ ] segment=total sums the brands and models present in both segments
- [ ] validation: wrong case, empty or repeated values, unknown period or view, month outside the coverage or
      malformed, limit 0 / 26 / 1.5 / abc / -1, and SQL-injection-shaped values all return 400 with the
      right `param` and no stack trace
- [ ] cache: a repeated call returns `cached: true` with the same numbers

UI (Chrome DevTools on localhost, screenshots kept in the run dir and not committed):

- [ ] The KPI row for the latest month matches the API, in pt-BR format (1.234 and 3,4%), and the YoY
      label says which basis it uses
- [ ] Every filter works (segment, period, view, month if exposed) and the page refetches
- [ ] The Aurora toggle changes the totals the view affects and leaves the real total as it is
- [ ] Aurora is highlighted (amber) in the series and the ranking; the residual is muted
- [ ] Loading, empty and error states (backend stopped, giving 503/500) show pt-BR copy and no stack trace
- [ ] 2004-01 prévia and the models fallback notice ("dados de <mês>") appear when reachable
- [ ] a11y: labelled controls, keyboard-only use of the filters, visible focus, no console errors, contrast
- [ ] No real brand name hard-coded in client code (`grep` against the brand list from SQL)
