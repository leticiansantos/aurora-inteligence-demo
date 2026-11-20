# /pos-venda on the real serving tables (Lakebase aftersales_lb_*, model v3)

- **Setup:** app from main 408618d (frontend T8 merged), served locally on :8913. It reads
  `AFTERSALES_SYNCED_SCHEMA=auto_intelligence` (the real `aftersales_lb_*` tables) and the app schema is
  `aftersales_app_dev`. No writes were made in this pass. Checks ran in Chrome through the DevTools MCP in an
  isolated context, on localhost only. Date: 2026-11-20.
- **Screenshot:** `.team/runs/2026-11-20-pos1/evidence/qa-ui-chart-real.png` (not committed; repo evidence is text
  only).

| Check | Observed | Oracle | Result |
|---|---|---|---|
| KPI parts at risk (h=28) | 102 = 13 critical + 89 high | risk_oracle h=28: critical 4+9 = 13, high 14+75 = 89 | PASS |
| KPIs, other | R$ 308.568 avoided, fill rate 90,3%, days of stock 35,0. "sem janela anterior" shows because previous = null | fill rate 0.9031 (sql 06) | PASS |
| Accuracy badge | "Erro 34% menor que a linha de base"; WAPE 20,0% vs. 30,1% | 0.200374 / 0.301496 (sql 05, MLflow v3) | PASS |
| `/api/aftersales/forecast` (all) | 34 points, 26 actual, 13 backtest, 8 future, 2026-05-18..2027-01-04 | Delta `aftersales_forecast_weekly` summed by week: 0 mismatches over 34 weeks × 4 fields (actual, forecast, lower, upper) | PASS |
| Chart drawn (ECharts canvas) | canvas 1076×280 with 15,011 painted pixels. Solid real line until 09/11, dashed forecast from 17/08 (backtest) through 04/01/2027, dotted 80% band | — | PASS |
| "Ver como tabela" | 34 rows: 26 with actuals, 21 with forecast (13 backtest + 8 future), 8 marked "(futuro)". Values equal Delta rounded (e.g. 04/01/2027 18.999, 14.325 a 23.674; 18/05/2026 13.131) | Delta sums | PASS |
| Ranking | "50 de 720", sorted by estimated lost sales. Top row Bateria 60Ah × Brasília, R$ 41.368, critical, showing frontend's open reorder "Reposição: Aberto" | risk table / openRequest | PASS |
| Console | 0 errors, 0 warnings | — | PASS |

## Observations
- **LOW (UX, frontend) → follow-up F6:** at a 1200 px viewport the ranking table is 1178 px wide inside a 1074 px
  container with `overflow-x: auto`. The "Ação recomendada e pedido" column, which holds the main action button and
  the request status, is cut off by 104 px with no cue that the table scrolls sideways. TL logged F6: add a scroll
  cue or make the action column sticky at ≤ 1200 px.
- **LOW (doc) → follow-up F5, not a failure:** `meta.syncedAt` = 2026-11-20T18:17:34.940Z = `max(scored_at)`. That
  matches ADR D6 ("O app mostra `syncedAt`, que é o `max(scored_at)` da tabela de risco servida", checked on main).
  The defect is the comment in `app/shared/aftersales.ts` ("ISO timestamp of the last Lakebase sync"), which
  overstates what the field means. The real freshness SLA test is the Delta-vs-Postgres count and `max(scored_at)`
  comparison in `tests/aftersales/check_lakebase.sh`.
