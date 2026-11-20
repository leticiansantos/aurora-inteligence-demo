import type { Application, Request, Response } from 'express';
import type { ApiErrorBody } from '../../shared/market.js';
import { sanitizeError } from '../health.js';
import {
  BRANDS_LIMIT,
  MODELS_LIMIT,
  ParamError,
  parseMarketQuery,
  type ParseOptions,
  type ParsedMarketQuery,
} from './params.js';
import { WarehouseError, type MarketService } from './service.js';

export type MarketEndpoint = 'summary' | 'timeseries' | 'brands' | 'models';

const OPTIONS: Record<MarketEndpoint, ParseOptions> = {
  summary: { month: true, limit: null },
  timeseries: { month: false, limit: null },
  brands: { month: true, limit: BRANDS_LIMIT },
  models: { month: true, limit: MODELS_LIMIT },
};

export interface MarketResult {
  status: 200 | 400 | 500 | 503;
  body: unknown;
}

/** Framework-free handler (unit-testable): validates, runs the service, maps errors. */
export async function handleMarket(
  endpoint: MarketEndpoint,
  rawQuery: Record<string, unknown>,
  service: MarketService,
  log: (message: string) => void = () => undefined
): Promise<MarketResult> {
  let query: ParsedMarketQuery;
  try {
    query = parseMarketQuery(rawQuery, OPTIONS[endpoint]);
  } catch (err) {
    if (err instanceof ParamError) return { status: 400, body: err.toBody() };
    throw err;
  }
  try {
    return { status: 200, body: await service[endpoint](query) };
  } catch (err) {
    if (err instanceof ParamError) return { status: 400, body: err.toBody() };
    if (err instanceof WarehouseError) {
      const reason = sanitizeError(err.cause);
      log(`market ${endpoint} failed: ${reason}`);
      return {
        status: 503,
        body: { error: { code: 'warehouse_unavailable', message: reason } } satisfies ApiErrorBody,
      };
    }
    // Anything else (unexpected data, code bug): 500 with a generic body; details only in the log.
    log(`market ${endpoint} failed: ${err instanceof Error ? err.name : 'unknown error'}`);
    return {
      status: 500,
      body: { error: { code: 'internal_error', message: 'internal error' } } satisfies ApiErrorBody,
    };
  }
}

export function registerMarketRoutes(app: Application, service: MarketService): void {
  for (const endpoint of Object.keys(OPTIONS) as MarketEndpoint[]) {
    app.get(`/api/market/${endpoint}`, async (req: Request, res: Response) => {
      const { status, body } = await handleMarket(endpoint, req.query as Record<string, unknown>, service, (m) =>
        console.error(m)
      );
      res.setHeader('Cache-Control', 'no-store');
      res.status(status).json(body);
    });
  }
}
