# Evidence

This folder holds text evidence that the project works on a real Databricks
workspace: command outputs, query results and smoke-test logs. A reviewer can
read and diff it without access to the workspace.

## Rules

1. **Text only.** Each file is `.txt` (raw command output) or `.md` (a short
   explanation plus the output in fenced blocks). Screenshots do not count as
   evidence and are not committed here.
2. **One folder per stage** of the data journey, one file per claim:

   ```
   evidence/
     README.md                  # this file
     foundation/                # Tela 0: bundle, UC schema/volumes, app, grants, deploy
       static-checks.txt        # tests/smoke/static_checks.sh (secrets, brand names, assets)
       bundle-validate.txt      # databricks bundle validate -t <target>
       bundle-summary.txt       # databricks bundle summary -t <target>
       uc-schema-volumes.txt    # schema + volumes listing
       uc-grants.txt            # grants for the app service principal + warehouse ACL
       app-status.txt           # databricks apps get <app> (state, SP client id, deployments)
       health-smoke.txt         # tests/smoke/health_smoke.sh output
       sp-query-history.txt     # warehouse statements executed as the app SP
       ui-http-check.txt        # auth gating, shell, assets, pt-BR copy in the served bundle
       deploy-idempotency.md    # deploy.sh runs 1-3 and before/after state of the no-change run
     <next-stage>/              # e.g. ingestion/, ml/, genie/ in later runs
   ```

3. **Every file starts with a header** that makes it reproducible:

   ```
   # claim:    <what this file proves, one line>
   # command:  <exact command, with --profile and -t>
   # git_sha:  <short sha of the commit that was deployed>
   # date:     <YYYY-MM-DD HH:MM UTC>
   # result:   PASS | FAIL
   ```

   Then the unedited output follows. If output has to be cut for length, mark
   the cut with `[... N lines omitted ...]` and never cut a failing line.
4. **No secrets or personal data.** Never record tokens, the `Authorization`
   header or `databricks auth token` output. Workspace host, catalog/schema
   names, app names and service principal application ids are fine. The
   scripts under `tests/smoke/` redact matches and never print tokens.
5. **Fictional brand only.** Evidence is committed to the public repo. The demo
   uses the fictional brand "Aurora Motors" (assistant "Lumi"), and evidence
   contains no real customer brand names, logos or data.
6. **Re-run, don't hand-edit.** When the system changes, regenerate the file
   from the command in its header. A file whose `git_sha` is older than the
   deployed commit is stale.

## Producing the foundation evidence

```bash
P=classic-stable-new   # CLI profile
T=dev                  # bundle target
tests/smoke/static_checks.sh                         > evidence/foundation/static-checks.txt
tests/smoke/collect_foundation_evidence.sh "$P" "$T"  # all other *.txt, read-only
```

`collect_foundation_evidence.sh` changes nothing in the workspace. It redacts
emails and local paths and never writes tokens. `deploy-idempotency.md` is
written by hand from the deploy logs and before/after snapshots, because the
test needs a deploy run.

`deploy.sh` calls `tests/smoke/health_smoke.sh` as its last step, so every
deploy ends with the same health check that is recorded here.

## What the smoke test asserts

`tests/smoke/health_smoke.sh <profile> <app-name>` reads the app URL and its
service principal client id with `databricks apps get`, calls `GET /api/health`
with the caller's OAuth token, and passes only if:

- HTTP 200 with a JSON body whose status is `ok` and that reports the app version;
- the identity reported by the server (`current_user()` run by the app) is the
  app service principal, not the calling user;
- `unityCatalog.reachable` is true with no error, `catalog`/`schema` match the target
  (`--schema CATALOG.SCHEMA`, default `classic_stable.auto_intelligence`) and
  `schemaExists` is true, i.e. a live Unity Catalog query confirmed the schema.

The response contract is `app/shared/health.ts` (`HealthResponse`).

It exits `0` on pass, `1` on a failed assertion and `2` on usage or tooling errors.
