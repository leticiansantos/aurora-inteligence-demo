# UI round-trip on /pos-venda (local, dev fixture): request → Lakebase row → UI status

- **Setup:** frontend team/pos1-frontend be973f6 (includes backend 1cd8da0), served locally on :8913 by the AppKit
  dev server. It reads the dev fixture `aftersales_lb_dev` (3 dealers × 4 parts) and writes to
  `aftersales_app_qa_dev` (QA's own app schema, ADR D6 local validation). Checks ran in Chrome through the
  DevTools MCP in an isolated context, on localhost only. Date: 2026-11-20 17:37 UTC.
- **Screenshot:** the full page after the request is at `.team/runs/2026-11-20-pos1/evidence/qa-ui-post-roundtrip.png`
  (not committed, because repo evidence is text only).

| Step | Action | Observed (a11y snapshot, network, DB) | Result |
|---|---|---|---|
| 1 | Open /pos-venda | KPIs: 12 parts at risk (9 critical + 3 high), R$ 25.545 avoided, 91,3% fill rate, 10,5 days of stock. The "sem janela anterior" note shows because previous = null. The badge "Modelo não supera a linha de base" is right for the fixture (WAPE 11,0% vs. 8,7%). Ranking shows 12 of 12 rows | PASS |
| 2 | "Solicitar reposição" for Filtro de ar → Recife | A confirmation dialog shows the part, destination, type and suggested 8 un. | PASS |
| 3 | Set quantity to 0 | The field is marked invalid ("Informe um número inteiro entre 1 e 100.000.") and "Confirmar pedido" is **disabled** | PASS |
| 4 | Set quantity to 8 and the note "QA-T6 UI double-click", then **double-click** Confirm | Network shows exactly **one** POST /api/aftersales/requests (201), then the risk list and request list reload. The status reads "Pedido registrado … com status “Aberto”". The row now shows "Reposição: Aberto" and appears first under "Pedidos recentes". Console: 0 errors or warnings | PASS |
| 5 | Postgres row (READ ONLY) | Exactly 1 row for D003/P004/reorder: quantity 8, open, requested_by local-dev, snapshot h=28 / high / 480.00, which matches the row shown in the UI | PASS |
| 6 | Stale page: create D002/P004 reorder through the API (201), then confirm the same request from the unrefreshed UI | The alert reads "Não foi possível registrar o pedido. Já existe um pedido em andamento para esta peça nesta concessionária…". No second row is written | PASS |

## Postgres rows for part P004 after the run
```
dealer_id | part_id | type | quantity | status | requested_by | horizon_days | risk_level | lost_sales_brl | note
D003 | P004 | reorder | 8 | open | local-dev | 28 | high | 480.00 | QA-T6 UI double-click
D002 | P004 | reorder | 3 | open | local-dev | 28 | high | 480.00 | QA-T6 stale-tab pre-create
(2 rows)
```

## UX observation (LOW)
- The Disco de freio × Campinas row recommends "Repor estoque 14 un." but shows "Transferência: Aberto". The pair has
  both an active reorder and an active transfer (they are different types, so the unique index allows both), and
  `openRequest` carries only the newest one. A user could think the recommended reorder was not placed.
