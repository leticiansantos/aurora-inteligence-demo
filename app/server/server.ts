import { readFileSync } from 'node:fs';
import { analytics, createApp, genie, lakebase, server, sql } from '@databricks/appkit';
import { runHealthCheck, sanitizeError } from './health.js';
import { registerMarketRoutes } from './market/routes.js';
import { registerAftersalesRoutes, registerAftersalesUnavailable } from './aftersales/routes.js';
import { withConnectionRetry } from './aftersales/util.js';
import { RequestRepository, type Queryable } from './aftersales/requests.js';
import { AftersalesService } from './aftersales/service.js';
import { MarketService, type RowRunner } from './market/service.js';

const DEFAULT_CATALOG = 'classic_stable';
const DEFAULT_SCHEMA = 'auto_intelligence';

/** Unity Catalog identifiers: letters, digits and underscores only. */
function identifierFromEnv(name: string, fallback: string): string {
  const value = process.env[name]?.trim() || fallback;
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(value)) {
    throw new Error(`${name} must be a plain Unity Catalog identifier`);
  }
  return value;
}

function readVersion(): string {
  try {
    const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as {
      version?: string;
    };
    return pkg.version ?? 'unknown';
  } catch {
    return 'unknown';
  }
}

const catalog = identifierFromEnv('DATABRICKS_CATALOG', DEFAULT_CATALOG);
const schema = identifierFromEnv('DATABRICKS_SCHEMA', DEFAULT_SCHEMA);
const version = readVersion();

// The Lakebase plugin is registered only when the app has a Lakebase endpoint (LAKEBASE_ENDPOINT), so the
// Market screen keeps working in environments without it.
const lakebaseEnabled = Boolean(process.env.LAKEBASE_ENDPOINT?.trim());

// The Genie plugin is registered only when a market Genie Agent is configured (DATABRICKS_GENIE_SPACE_ID); the
// client calls it under the alias `market` (/api/genie/market/*). Created by scripts/genie/deploy_space.sh.
const genieSpaceId = process.env.DATABRICKS_GENIE_SPACE_ID?.trim();
const geniePlugins = genieSpaceId ? [genie({ spaces: { market: genieSpaceId } })] : [];

/** `withLakebase=false` starts the app without the plugin; aftersales routes then answer 503 (Market is unaffected). */
function start(withLakebase: boolean): Promise<unknown> {
  return createApp({
    plugins: withLakebase
      ? [analytics(), lakebase(), ...geniePlugins, server()]
      : [analytics(), ...geniePlugins, server()],
    onPluginsReady(appkit) {
      const run: RowRunner = async (statement, params) => {
        const markers = Object.fromEntries(
          Object.entries(params).map(([k, v]) => [k, typeof v === 'number' ? sql.number(v) : sql.string(v)])
        );
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 60_000);
        try {
          const result = (await appkit.analytics.query(statement, markers, undefined, controller.signal)) as {
            data?: Record<string, unknown>[];
          };
          return Array.isArray(result?.data) ? result.data : [];
        } finally {
          clearTimeout(timer);
        }
      };
      const market = new MarketService(run, { catalog, schema });
      appkit.server.extend((app) => {
        registerMarketRoutes(app, market);
        if (withLakebase) {
          try {
            const db = withConnectionRetry((appkit as unknown as { lakebase: Queryable }).lakebase);
            const requests = new RequestRepository(db);
            // Idempotent DDL, run lazily with retry on first use; also tried once now (warm-up, failure tolerated).
            requests
              .init()
              .catch((err: unknown) => console.warn('aftersales schema warm-up failed:', sanitizeError(err)));
            registerAftersalesRoutes(app, new AftersalesService(db, requests), requests);
          } catch (err) {
            console.error('aftersales setup failed, serving 503:', sanitizeError(err));
            registerAftersalesUnavailable(app);
          }
        } else {
          registerAftersalesUnavailable(app);
        }
        app.get('/api/health', async (_req, res) => {
          const { httpStatus, body } = await runHealthCheck(appkit.analytics, {
            version,
            catalog,
            schema,
            stringParam: (value) => sql.string(value),
          });
          res.setHeader('Cache-Control', 'no-store');
          res.status(httpStatus).json(body);
        });
      });
    },
  });
}

// A Lakebase plugin failure (bad endpoint, auth, config) must not take the Market screen down: retry once
// without the plugin. Failures that are not Lakebase-related fail the second start too and exit as before.
start(lakebaseEnabled)
  .catch((err: unknown) => {
    if (!lakebaseEnabled) throw err;
    console.error(
      'lakebase setup failed, starting without aftersales:',
      err instanceof Error ? err.message : 'unknown error'
    );
    return start(false);
  })
  .catch((err: unknown) => {
    console.error('app failed to start:', err instanceof Error ? err.message : 'unknown error');
    process.exit(1);
  });
