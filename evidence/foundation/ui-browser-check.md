# UI browser check (local production run)

**Scope and caveat.** This is a LOCAL run, not the deployed app. The deployed URL sits behind the Databricks/Microsoft login, which the MCP-driven Chrome could not pass (no SSO session; no credentials were typed). Instead the production build was served locally and browsed with Chrome DevTools. The local server authenticates to the real backend as the **local CLI user** (profile `classic-stable-new`), not as the app service principal. The service-principal identity is proven separately by `health-smoke.txt` and `sp-query-history.txt`.

- Date: 2026-11-20
- Code: `team/fnd0-frontend` merged with main (`e41b203`), built with `npm run build`, started with `node ./dist/server.js`
- Env (no tokens): `DATABRICKS_CONFIG_PROFILE=classic-stable-new`, `DATABRICKS_WAREHOUSE_ID=754bcdfc4beaaaa1`, `DATABRICKS_CATALOG=classic_stable`, `DATABRICKS_SCHEMA=auto_intelligence`, `DATABRICKS_APP_PORT=8765`
- Browser: Google Chrome via DevTools MCP, isolated context, `http://localhost:8765`
- Server log: `Server running on http://0.0.0.0:8765`, `Mode: production (static)`

## Real /api/health (curl, HTTP 200)

```json
{"status":"ok","version":"1.0.0","unityCatalog":{"reachable":true,"identity":"<local CLI user, redacted>","currentCatalog":"classic_stable","catalog":"classic_stable","schema":"auto_intelligence","schemaExists":true,"latencyMs":1696,"error":null}}
```

## Checklist

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | App loads, `/` redirects to first section | PASS | page URL `http://localhost:8765/mercado`, title "Aurora Motors · Auto Intelligence" |
| 2 | Section Visão de Mercado | PASS | h2 "Visão de Mercado", empty state "Em construção" |
| 3 | Section Pós-venda | PASS | URL `/pos-venda`, h2 "Pós-venda", `aria-current=page` on its nav link |
| 4 | Section Visão do Motorista | PASS | URL `/motorista`, h2 "Visão do Motorista" |
| 5 | Section Genie | PASS | URL `/genie`, h2 "Genie", text "Pergunte aos dados em linguagem natural com a Lumi." |
| 6 | Health badge shows ok from real API | PASS | accessible name: "Estado do serviço: Operacional. v1.0.0 · classic_stable.auto_intelligence encontrado · 1245 ms. Clique para atualizar." |
| 7 | Benefícios popup | PASS | `dialog "Benefícios"` opens with placeholder "Conteúdo em breve"; Escape closes it; focus returns to the Benefícios button |
| 8 | Keyboard navigation | PASS | from fresh load of `/pos-venda`: Tab x5 focuses "Genie" (skip link, Mercado, Pós-venda, Motorista, Genie); Enter navigates to `/genie`; Tab x2 reaches Benefícios (after the health badge); Enter opens the dialog with focus on its close button |
| 9 | Deep link reload (SPA fallback) | PASS | direct navigation to `/pos-venda` renders the page |
| 10 | Console clean | PASS | `list_console_messages` (incl. preserved): no messages |
| 11 | Network | PASS | only requests: `GET /api/health` [200] (x2, initial + badge), assets 200/304, favicon.svg |

## A11y snapshot excerpt (genie page, dialog open)

```
dialog "Benefícios" description="Resumo dos ganhos da jornada de dados de ponta a ponta."
  heading "Benefícios" level="2"
  heading "Conteúdo em breve" level="3"
  button "Close" focusable focused
```

## Known gaps

- The dialog's built-in close button is announced "Close" in English (AppKit UI string).
- Deployed-URL UI check not done (login wall); the deployed HTTP check is in `ui-http-check.txt`.
- Not exercised here: the badge's degraded/down/error states against the real server (verified earlier against a mock, see run report T5).
- Screenshot kept outside the repo: run dir `evidence/frontend-t11-local-health-ok.png`.

Local server stopped after the run (port 8765 no longer answers).
