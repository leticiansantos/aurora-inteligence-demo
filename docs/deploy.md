# Deploy

One command deploys the foundation: Unity Catalog schema and volumes, the app, grants and a smoke test.

```bash
./deploy.sh                                   # profile classic-stable-new, target demo
./deploy.sh --profile classic-stable-new --target dev
./deploy.sh --skip-smoke                      # skip the /api/health check
```

The default profile is `classic-stable-new`. The script never picks another profile by itself.
It needs a valid OAuth login (`databricks auth login --profile classic-stable-new`) and no PATs.

## Steps

1. `bundle validate --strict`
2. `bundle deploy`: creates `classic_stable.auto_intelligence`, volumes `raw_landing` and `manuals`, and the app.
3. `scripts/grant_app_sp.sh`: gives the app's auto-created service principal `USE CATALOG`, `USE SCHEMA`, `SELECT` and `READ VOLUME` on this one schema. It also adds an explicit warehouse `CAN_USE` entry for that service principal (additive, never removes existing entries), prints "unchanged" or "granted", and fails if the entry is missing afterwards.
4. `bundle run app`: deploys the app source from `app/` and starts it. Skipped on re-run when `app/` and the bundle config are unchanged (hash in `.databricks/`) and the app is already running.
5. Smoke test: `tests/smoke/health_smoke.sh` calls `/api/health` with a user OAuth token and checks status, identity (the app service principal), catalog and schema. Needs `jq`.

Every step is safe to re-run.

## Targets

| Target | Schema | App name |
|---|---|---|
| `demo` (default) | `classic_stable.auto_intelligence` | `auto-intelligence` |
| `dev` | `classic_stable.auto_intelligence_dev` | `auto-intelligence-dev` |

The bundle does not use `mode: development`, because that would prefix object names and break the fixed schema name.
Override `catalog`, `schema`, `warehouse_id` or `app_name` with `databricks bundle deploy --var key=value`.

## Notes

- `bundle validate` needs `app/` to exist (the AppKit app).
- The grants script can run alone: `scripts/grant_app_sp.sh --profile classic-stable-new`.
