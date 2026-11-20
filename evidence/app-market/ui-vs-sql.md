# Market screen (/mercado): UI vs API vs SQL

- Build: team/mkv1-frontend @3c77b7d (includes backend eb93a60), served locally on :8903 (`tsx server/server.ts`, dev mode)
- Browser: cmux built-in browser (WebKit), 2026-11-20 16:19 UTC. Chrome DevTools MCP was not available: its shared profile was held by another session.
- UI text was read with `cmux browser get text --selector main`. SQL comes from tests/app-market/sql/*.sql. The API values are in api-vs-sql.txt (1411/1411 PASS).
- Screenshots qa-01..07 are in the run dir (.team/runs/2026-11-20-mkv1/evidence/) and are not committed.
- Real brand names are left out. Only the top brand's numbers, Aurora Motors and the residual are quoted.

## KPIs (UI text vs SQL oracle 01_summary.sql)

| month | segment | view | UI mercado | SQL total_units | UI YoY | SQL yoy_pct | UI share Aurora | SQL | UI p.p. | SQL pp | UI rank | SQL rank/of |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09 | total | with_aurora | 275.413 | 275413 | +16,2% | 0.16219 | 2,4% | 0.02430 | +0,1 p.p. | +0.00063 | 12º entre 34 | 12/34 |
| 2026-09 | total | real | 268.721 | 268721 (real) | +16,1% | 268721/231370-1 = 0.16143 | — | null | — | — | — | null |
| 2026-09 | automoveis | with_aurora | 223.058 | 223058 | +21,1% | 0.21124 | 3,0% | 0.03000 | 0,0 p.p. | -0.00045 | 12º entre 22 | 12/22 |
| 2026-08 | automoveis | with_aurora | 219.994 | 219994 | (not read) | 0.23620 | | | | | | |
| 2023-03 | automoveis | with_aurora | 151.827 | 151827 | +35,2% | 0.35158 | 3,7% | 0.03723 | +0,1 p.p. | +0.00083 | 10º entre 22 | 10/22 |
| 2007-06 | comerciais_leves | real | 19.348 | 188777-169429 = 19348 | +17,4% | 19348/16480-1 = 0.17403 | — | null | — | — | — | null |
| 2004-01 | total | with_aurora | 101.109 | 101109 | -5,2% | -0.05157 | — | null (pre-2019) | — | — | — | null |

Switching the view (2026-09 total): the real view shows 268.721, which equals realUnits in both views. The with_aurora view shows 275.413 = 268.721 + 6.692 Aurora. The real market total is never changed.

## Brand ranking / models

- 2026-09 total with_aurora, month: #1 brand 53.586, 19,5% (SQL 53586, 0.19457). Residual 4.881, 1,8%. "Mais 54.947" = othersUnits. **Aurora (rank 12) is not shown.**
- 24m period (out/24..set/26) total with_aurora: #1 1.106.863, 19,8% (SQL 1106863, 0.19809). Residual 62.403, 1,1% (SQL 62403, 0.01117). **Aurora (rank 11, 146.781) is not shown.**
- 2023-03 automoveis: Aurora Motors row 10, 5.653, 3,7%, badge "sintética", amber-tinted background. Residual 987, 0,7%, muted grey italic.
- 2004-01: note "Este mês só tem o total publicado, sem ranking de marcas (edição prévia)." Only row: Outras (não publicadas) 101.109, 100,0%.
- Models 2026-09 total: #1 16.002, 5,8% (SQL 16002, 0.05810). "cobrem 92%" (SQL 253242/275413 = 0.9195).
- Models 2004-01: falls back to dezembro de 2003, "cobrem 99%" (SQL 160157/161405 = 0.9923). The notice reads "O mês mais recente (janeiro de 2004) ainda não tem tabela de modelos" (wording defect: January 2004 is the selected month, not the most recent).

## States

- Month out of coverage (URL ?mes=2002-12): each card shows "Mês fora da cobertura dos dados (2003-01 a 2026-09)." with "Tentar novamente".
- Picking Dezembro/2026 in the month picker clamps to set/26 (URL drops mes). No error.
- Warehouse down (server restarted with a bogus warehouse id, API 503): the 4 cards show "Não foi possível carregar …" followed by **"warehouse query failed"** (English server text) and "Tentar novamente".
- Console: only `[vite] failed to connect to websocket` (my dev-mode HMR port 24678 was taken by another server). No app errors.

## Charts

- The charts are ECharts canvases with role=img and an aria-label ("Emplacamentos mensais, de out/24 a set/26"; "Participação mensal da Aurora Motors…"). There is no table or text fallback.
- The hidden cmux webview never fires requestAnimationFrame (`document.visibilityState = hidden`, rAF timed out after 1.5 s), so ECharts drew nothing. This is a test-harness artifact. With an init-script rAF→setTimeout shim, both canvases render: steel-blue units area and amber Aurora share line, with pt-BR month axis (out/24 … jul/26).

## Keyboard / a11y (cmux synthetic keys)

- Filter radios: arrow keys move focus (roving tabindex), Space selects. Segment changed via keyboard: URL ?segmento=automoveis.
- Month combobox: Enter opens a listbox of 12 options, ArrowUp+Enter selects (URL mes=2026-08, KPI ago/26).
- Visible focus: radios show a 3px ring (box-shadow).
- Tab sequence with cmux `press Tab` went Total → 24 meses → Com a Aurora → Mês de referência and skipped the Mês/Ano comboboxes, which have tabIndex=0. Not confirmed as a defect: it may be the synthetic Tab (Chrome not available).
- Not run: Lighthouse/axe audit (needs Chrome DevTools). Contrast spot-check: body/muted text rgb(86,98,110) on white is about 6:1.

## Re-verification on team/mkv1-frontend @5a5131e (2026-11-20 16:53 UTC, Chrome DevTools MCP, isolated context)

Build checks: client tsc 0, client eslint 0, vitest 37/37. API harness re-run on this build: 1411 checks, 0 FAIL.

| # | QA finding (3c77b7d) | Observed on 5a5131e | Result |
|---|---|---|---|
| 7 | Aurora hidden in default ranking | 2026-09 total with_aurora: top 10, then "12 Aurora Motors sintética 6.692 2,4%", then residual 4.881 1,8%, then "48.255 emplacamentos em outras marcas publicadas". 215.585 (top 10) + 6.692 + 4.881 + 48.255 = 275.413 = total. 2025-06 automoveis: Aurora at rank 10, 5.579 (SQL 5579). View real: no Aurora row, same 48.255 others (real 268.721) | FIXED |
| 8 | English server text in error state | warehouse down (503): every card reads "O serviço de dados está indisponível no momento. Tente novamente em instantes." Month out of coverage (400): "Os filtros escolhidos não são válidos. Ajuste a seleção e tente novamente." | FIXED |
| 9 | YoY basis not labelled | "VARIAÇÃO ANUAL (COM A AURORA)" / "VARIAÇÃO ANUAL (MERCADO REAL)", detail "vs. mesmo mês de 2025" | FIXED |
| 10a | fallback notice said "mais recente" | 2004-01: "Modelos de dez/03: a edição de jan/04 não publicou ranking de modelos." | FIXED |
| 10b | charts without a text fallback | "Ver como tabela" (details/summary, tabIndex 0): 24 rows + header. set/26 223.058 3,0% and out/24 201.238 3,0% match 02_timeseries.sql (223058, 0.0300; 201238, 0.0300) | FIXED |
| 10c | subtitle mentioned "região" | "Emplacamentos por marca e segmento, com a participação da Aurora Motors." | FIXED |
| 10d | reference month not marked on the chart | mes=2025-06: dark point on jun/25 in both charts (units approx. 165 mil; SQL 164707, share 0.0339). The description says the series runs to set/26 and ignores the reference month | FIXED |
| open Q | Tab skipped Mês/Ano (cmux) | Real Chrome Tab: Com a Aurora → Mês → Ano; :focus-visible draws a 3px steel-blue ring | NOT A DEFECT (cmux artifact) |

Lighthouse (navigation, desktop): Accessibility 96. One failing a11y audit: color-contrast on the "sintética" badge, #b5651d on #f8f0e8 = 3.84:1 at 10px (needs 4.5:1). Best Practices 96. Its "errors-in-console" item is environment noise from my setup: the Vite HMR websocket (port 24678 is taken by another dev server) and 10 x 403 on Barlow font files (my scratch checkout symlinks node_modules outside Vite's fs.allow), plus one "Uncaught (in promise)" seen alongside the StrictMode double-mount aborts in dev.
