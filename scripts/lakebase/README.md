# Lakebase scripts (Aftersales)

Profile `classic-stable-new`, all idempotent. Lakebase is managed by CLI scripts only (ADR D6; no DAB, no new UC catalog).

1. `scripts/lakebase/create_project.sh`: project `auto-intelligence-aftersales` (0.5-1 CU, scale-to-zero)
2. Gold/ML tables exist (pipeline + scoring), then `scripts/lakebase/sync_tables.sh` (Plan A: synced tables SNAPSHOT as
   `aftersales_lb_*` in Postgres schema `auto_intelligence`)
3. App deployed once (its SP creates and owns schema `aftersales_app`), then `scripts/lakebase/grant_app_sp.sh`
4. After each scoring run: job task `sync` (`src/aftersales/serving/refresh_synced_tables.py`)

Local development uses `AFTERSALES_APP_SCHEMA=aftersales_app_dev` so the deployed SP stays the owner of `aftersales_app`.
`dev_seed.sql` builds a tiny synthetic stand-in of the serving tables in an isolated schema for API tests.

## Enable Lakebase in the deployed app (follow-up F1, not part of this run)

`resources/app.yml` ships WITHOUT Lakebase so the app deploys as before (Market only; `/api/aftersales/*` is not
registered because `LAKEBASE_ENDPOINT` is unset). To enable it:

1. Merge the two hunks described in `scripts/lakebase/app.lakebase.hunk.yml` into `resources/app.yml`
   and run `./deploy.sh --profile classic-stable-new` (creates the Postgres role for the app SP).
2. Open `/pos-venda` once: the app migration creates `aftersales_app`, owned by the SP.
3. `scripts/lakebase/grant_app_sp.sh`, then verify (ADR section 7, F1 step 4) and do a smoke POST.
