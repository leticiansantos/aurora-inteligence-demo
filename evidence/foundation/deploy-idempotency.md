# claim:    a second deploy.sh run with no source change is a no-op (no new resources, files, deployment or grants)
# command:  ./deploy.sh --profile classic-stable-new --target demo   (run 3x from the main checkout by the lead)
# git_sha:  9fba14c
# date:     2026-11-20 12:24 UTC (run 3)
# result:   PASS

Run 1 created everything. Run 2 followed a real source change (frontend merge), so it redeployed the app.
Run 3 had no change and is the idempotency test.

## Key lines from each run (from the deploy logs)

| step | run 1 (first deploy) | run 2 (source changed) | run 3 (no change) |
|---|---|---|---|
| bundle files | 56 uploaded, 0 deleted | 19 uploaded, 6 deleted | **0 uploaded, 0 deleted** |
| bundle resources | 4 created, 0 changed, 0 deleted | 0 created, 0 changed, 0 deleted, 4 unchanged | **0 created, 0 changed, 0 deleted, 4 unchanged** |
| grants (additive `grants update`) | applied | re-applied, no-op | re-applied, no-op (state diff below) |
| app deployment | new deployment, "App started successfully" | new deployment, "App started successfully" | **"App source unchanged and running: skipping app deployment"** |
| smoke test | SMOKE TEST PASSED | SMOKE TEST PASSED | SMOKE TEST PASSED |
| identity == app SP | 9d41f279-1e55-4654-9579-3587ef47e5e8 | same | same |

## Workspace state before vs after run 3

Read-only snapshots (`databricks ... -o json`, normalized with `jq -S`, sha1 prefix) taken right before and right after run 3:

| object | before | after | result |
|---|---|---|---|
| app | 2bf3b7c00039 | 2bf3b7c00039 | UNCHANGED |
| deps | 6f95ea1173a0 | 6f95ea1173a0 | UNCHANGED |
| g_cat | 3226f01eb660 | 3226f01eb660 | UNCHANGED |
| g_sch | f153689546c6 | f153689546c6 | UNCHANGED |
| schema | 0e356db996d1 | 0e356db996d1 | UNCHANGED |
| vols | ae51d820acc4 | ae51d820acc4 | UNCHANGED |
| wh | 871a903e2296 | 871a903e2296 | UNCHANGED |

- app `update_time`: before `2026-11-20T12:22:06Z`, after `2026-11-20T12:22:06Z`
- active deployment after run 3: `01f1e4dd00441518adcedb62efe0d819` (the one from run 2)

All deployments of the app (run 3 added none):

| deployment_id | state | create_time |
|---|---|---|
| 01f1e4dd00441518adcedb62efe0d819 | SUCCEEDED | 2026-11-20T12:22:06Z |
| 01f1e4dc908b172d9a5bc3db2982240d | SUCCEEDED | 2026-11-20T12:18:59Z |

## Notes

- How the skip works: deploy.sh hashes `app/` (minus node_modules/dist), `databricks.yml` and `resources/*.yml` and stores the hash in
  `.databricks/deploy-<target>.hash` only after a successful `bundle run`. It skips the app step when the hash matches and the app
  is `RUNNING` with a `SUCCEEDED` deployment. Because the hash is local state, a fresh clone redeploys the app once.
- `bundle deploy` on its own created no app deployment (CLI v1.24): run 3 still has 2 deployments.
- grant_app_sp.sh prints "Granted ..." on every run even when nothing changes. The UC state diff above shows it is a no-op.
- Every run prints `WARNING: app service principal not listed on warehouse`. See uc-grants.txt: the SP has no explicit warehouse ACL
  entry and uses the `users` group's CAN_USE.
