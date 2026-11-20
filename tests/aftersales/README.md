# Pós-venda (Tela 2) QA: adversarial checks

The checks verify the Tela 2 journey against [ADR 002](../../docs/architecture/aftersales.md) and the frozen
contract [`docs/data-model/aftersales.md`](../../docs/data-model/aftersales.md). Each oracle re-derives its
result from the layer below (for example, the risk from the forecast plus the stock), so a defect in a table
shows up as a diff. All of them are read-only. The one exception is `check_api.py --write`, which creates
request rows through the app as a real user would, each with a note starting with `QA-T6`. Evidence is written
as text to `evidence/aftersales/`.

| File | What it checks | Evidence |
|---|---|---|
| `check_data_rules.py` | every `aftersales_*` table has a comment, the tags `synthetic`/`aid_domain`/`layer` (ADR D9: `domain` is a governed key) and column comments (raw tables exempt); no real brand from `market_brand_monthly` appears; no part code or dealer name from the old demo CSVs appears (`--legacy-dir`, counts only) | `data-rules.txt` |
| `run_sql_checks.py` + `sql/01..06` | PKs and grain, silver rules, fleet vs. Tela 1 registrations (380,258 units), weekly gold re-aggregation, forecast layout, holdout after the cutoff, recomputed WAPE/bias/interval, seasonal-naive baseline, the `@champion` gate, plausibility targets (D1) | `sql-checks.txt` |
| `risk_oracle.py` | an independent Python implementation of D5 (all 2,160 rows, every field, the greedy same-region transfer, donors limited to on-hand stock) diffed against `aftersales_stockout_risk`, plus the D1 targets at h=28 | `risk/oracle-diff.txt` |
| `unit/test_risk_oracle.py` | an offline self-test of the D5 oracle on hand-computed cases | n/a |
| `check_lakebase.sh` | Postgres serving tables vs. Delta (count, sums, `max(scored_at)`), the OLTP partial unique index and CHECKs, the schema owner, no PII in `requested_by`, the app SP's least privilege | `lakebase/checks.txt` |
| `check_api.py` | the API contract: 400 + `param` matrix, KPI/risk invariants, sort order, 26+8 weekly series, request round-trip, 10 parallel duplicates giving 1×201 + 9×409 | `app/api-contract.txt` |

```bash
P="--profile classic-stable-new --warehouse 754bcdfc4beaaaa1"
python3 -I tests/aftersales/check_data_rules.py $P --legacy-dir <legacy-demo-dir>
python3 -I tests/aftersales/run_sql_checks.py $P            # --only 01,02,03 while layers land
python3 -I tests/aftersales/risk_oracle.py $P
python3 -I tests/aftersales/unit/test_risk_oracle.py
tests/aftersales/check_lakebase.sh aftersales_app_dev       # local validation schema (ADR D6)
python3 -I tests/aftersales/check_api.py --base http://localhost:8913 --write --out evidence/aftersales/app/api-contract.txt
```

The plausibility thresholds in `sql/06` that are not ADR targets reflect QA judgment: yearly demand correlates
with the fleet (> 0.8), seasonality shows a max/min monthly index of at least 1.10, the series are not all
alike (CV > 0.3), fewer than 20% of series have zero demand, prices fall between R$ 5 and R$ 10,000, and margins
fall between 10% and 70%.
