import { type Application, type Request, type Response } from 'express';
import type { AftersalesErrorBody } from '../../shared/aftersales.js';
import { sanitizeError } from '../health.js';
import { ApiError, invalid } from './errors.js';
import { isTransientConnectionError } from './util.js';
import {
  parseCreateBody,
  parseListQuery,
  parseRequestId,
  validateAgainstCatalog,
  type RequestRepository,
} from './requests.js';
import { parseRiskExtras, type AftersalesService } from './service.js';

interface Result {
  status: number;
  body: unknown;
  headers?: Record<string, string>;
}

const errorBody = (code: AftersalesErrorBody['error']['code'], message: string): AftersalesErrorBody => ({
  error: { code, message },
});

/** Maps thrown errors to HTTP results. Connection-level failures are 503, anything else 500 (no details leaked). */
export function mapError(err: unknown, log: (m: string) => void): Result {
  if (err instanceof ApiError) return { status: err.status, body: err.toBody() };
  const code = (err as { code?: string })?.code ?? '';
  // Transient connection failures (with or without SQLSTATE), 42501 permission, 3F000 missing schema, 42P01 missing table.
  if (isTransientConnectionError(err) || /^(42501|3F000|42P01)/.test(code)) {
    log(`aftersales lakebase failure: ${code} ${sanitizeError(err)}`);
    return {
      status: 503,
      body: errorBody('lakebase_unavailable', 'Banco operacional (Lakebase) indisponível. Tente novamente.'),
    };
  }
  log(`aftersales failed: ${err instanceof Error ? err.name : 'unknown error'} ${code}`);
  return { status: 500, body: errorBody('internal_error', 'internal error') };
}

export function registerAftersalesRoutes(
  app: Application,
  service: AftersalesService,
  requests: RequestRepository,
  log: (m: string) => void = (m) => console.error(m)
): void {
  const wrap =
    (fn: (req: Request) => Promise<Result>) =>
    async (req: Request, res: Response): Promise<void> => {
      let result: Result;
      try {
        result = await fn(req);
      } catch (err) {
        result = mapError(err, log);
      }
      res.setHeader('Cache-Control', 'no-store');
      for (const [k, v] of Object.entries(result.headers ?? {})) res.setHeader(k, v);
      res.status(result.status).json(result.body);
    };
  const q = (req: Request) => req.query as Record<string, unknown>;

  app.get(
    '/api/aftersales/filters',
    wrap(async () => ({ status: 200, body: await service.filters() }))
  );
  app.get(
    '/api/aftersales/summary',
    wrap(async (req) => ({ status: 200, body: await service.summary(await service.parse(q(req))) }))
  );
  app.get(
    '/api/aftersales/forecast',
    wrap(async (req) => {
      const f = await service.parse(q(req));
      const part = q(req).partId;
      if (part !== undefined && (typeof part !== 'string' || part.length === 0))
        throw invalid('partId', 'Parâmetro "partId" inválido.');
      return { status: 200, body: await service.forecast(f, part ?? null) };
    })
  );
  app.get(
    '/api/aftersales/risk',
    wrap(async (req) => {
      const f = await service.parse(q(req));
      return { status: 200, body: await service.risk(f, parseRiskExtras(q(req))) };
    })
  );

  // AppKit's server already parses JSON bodies (with its own, larger limit) before our routes run, so we
  // enforce Content-Type and our 16 KB cap here, and map its parse errors to the contract's error shape.
  const MAX_BODY_BYTES = 16 * 1024;
  app.use('/api/aftersales', (err: unknown, _req: Request, res: Response, next: (e?: unknown) => void) => {
    const type = (err as { type?: string })?.type;
    if (type === 'entity.parse.failed' || type === 'entity.too.large') {
      res.status(400).json(invalid('body', 'Corpo da requisição inválido ou grande demais.').toBody());
      return;
    }
    next(err);
  });
  const parseBody = (req: Request, res: Response, next: (e?: unknown) => void) => {
    const length = Number(req.header('content-length') ?? 0);
    if (!req.is('application/json')) {
      res.status(400).json(invalid('body', 'Content-Type deve ser application/json.').toBody());
    } else if (length > MAX_BODY_BYTES || Buffer.byteLength(JSON.stringify(req.body ?? null)) > MAX_BODY_BYTES) {
      res.status(400).json(invalid('body', 'Corpo da requisição grande demais (máximo 16 KB).').toBody());
    } else {
      next();
    }
  };
  app.post(
    '/api/aftersales/requests',
    parseBody,
    wrap(async (req) => {
      const body = parseCreateBody(req.body);
      const validated = await validateAgainstCatalog(body, service);
      // No PII: a constant identifies the caller kind (deployed app vs local development).
      const created = await requests.create(validated, process.env.NODE_ENV === 'production' ? 'app' : 'local-dev');
      return {
        status: 201,
        body: { request: created },
        headers: { Location: `/api/aftersales/requests/${created.id}` },
      };
    })
  );
  app.get(
    '/api/aftersales/requests',
    wrap(async (req) => ({
      status: 200,
      body: await (async () => {
        const query = parseListQuery(q(req));
        if (query.dealer !== undefined && !(await service.dealerExists(query.dealer))) {
          throw invalid('dealer', 'Valor inválido para "dealer".');
        }
        return { requests: await requests.list(query) };
      })(),
    }))
  );
  app.get(
    '/api/aftersales/requests/:id',
    wrap(async (req) => ({
      status: 200,
      body: { request: await requests.get(parseRequestId(req.params.id)) },
    }))
  );
}

/** Registers stub routes when Lakebase could not be set up: aftersales answers 503, everything else keeps working. */
export function registerAftersalesUnavailable(app: Application): void {
  app.use('/api/aftersales', (_req: Request, res: Response) => {
    res.setHeader('Cache-Control', 'no-store');
    res
      .status(503)
      .json(errorBody('lakebase_unavailable', 'Banco operacional (Lakebase) indisponível. Tente novamente.'));
  });
}
