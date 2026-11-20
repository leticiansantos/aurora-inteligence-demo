import type {
  AftersalesErrorBody,
  AftersalesFiltersResponse,
  AftersalesForecastQuery,
  AftersalesForecastResponse,
  AftersalesQuery,
  AftersalesRequestListQuery,
  AftersalesRequestListResponse,
  AftersalesRequestResponse,
  AftersalesRiskQuery,
  AftersalesRiskResponse,
  AftersalesSummaryResponse,
  CreateAftersalesRequestBody,
} from '../../../shared/aftersales';
import { mockAftersales } from './aftersalesMock';

export type * from '../../../shared/aftersales';
export { AFTERSALES_DEFAULT_HORIZON, AFTERSALES_HORIZONS } from '../../../shared/aftersales';

/** Set VITE_AFTERSALES_MOCK=1 to render the page from typed mock data (no server needed). */
const USE_MOCK = import.meta.env.VITE_AFTERSALES_MOCK === '1';

export class AftersalesApiError extends Error {
  readonly status: number;
  readonly code?: AftersalesErrorBody['error']['code'];
  constructor(message: string, status: number, code?: AftersalesErrorBody['error']['code']) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** pt-BR copy owned by the client; server text is never shown (it is for logs and tests). */
export function errorCopy(status: number, code?: AftersalesErrorBody['error']['code']): string {
  if (code === 'duplicate_request')
    return 'Já existe um pedido em andamento para esta peça nesta concessionária. Acompanhe o andamento na lista de pedidos.';
  if (code === 'lakebase_unavailable' || code === 'warehouse_unavailable' || status === 503)
    return 'O serviço de dados está indisponível no momento. Tente novamente em instantes.';
  if (status === 400) return 'Os dados informados não são válidos. Ajuste a seleção e tente novamente.';
  if (status === 404) return 'O pedido não foi encontrado.';
  return 'Não foi possível carregar os dados de pós-venda. Tente novamente.';
}

/** Copy for a failed POST: the generic read-error text ("carregar os dados") would be wrong here. */
export function writeErrorCopy(status: number, code?: AftersalesErrorBody['error']['code']): string {
  if (code === 'duplicate_request' || code === 'lakebase_unavailable' || status === 503) return errorCopy(status, code);
  if (status === 400) return 'Não foi possível registrar o pedido. Confira a quantidade e tente novamente.';
  if (status === 404) return 'Não foi possível registrar o pedido: a peça ou a concessionária não foi encontrada.';
  return 'Não foi possível registrar o pedido. Tente novamente em instantes.';
}

async function call<T>(path: string, init: RequestInit & { query?: object } = {}): Promise<T> {
  const { query, ...rest } = init;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null) qs.set(k, String(v));
  const url = `/api/aftersales/${path}${qs.size ? `?${qs}` : ''}`;
  let res: Response;
  try {
    res = await fetch(url, { ...rest, headers: { Accept: 'application/json', ...rest.headers } });
  } catch (err) {
    if (rest.signal?.aborted) throw err;
    throw new AftersalesApiError('Não foi possível conectar ao servidor. Verifique a conexão e tente novamente.', 0);
  }
  const isJson = (res.headers.get('content-type') ?? '').includes('application/json');
  if (!res.ok) {
    const body = isJson ? ((await res.json().catch(() => null)) as AftersalesErrorBody | null) : null;
    throw new AftersalesApiError(errorCopy(res.status, body?.error.code), res.status, body?.error.code);
  }
  if (!isJson) throw new AftersalesApiError(errorCopy(res.status), res.status);
  return (await res.json()) as T;
}

export const aftersalesApi = USE_MOCK
  ? mockAftersales
  : {
      filters: (s?: AbortSignal) => call<AftersalesFiltersResponse>('filters', { signal: s }),
      summary: (q: AftersalesQuery, s?: AbortSignal) =>
        call<AftersalesSummaryResponse>('summary', { query: q, signal: s }),
      forecast: (q: AftersalesForecastQuery, s?: AbortSignal) =>
        call<AftersalesForecastResponse>('forecast', { query: q, signal: s }),
      risk: (q: AftersalesRiskQuery, s?: AbortSignal) => call<AftersalesRiskResponse>('risk', { query: q, signal: s }),
      requests: (q: AftersalesRequestListQuery, s?: AbortSignal) =>
        call<AftersalesRequestListResponse>('requests', { query: q, signal: s }),
      createRequest: (body: CreateAftersalesRequestBody, s?: AbortSignal) =>
        call<AftersalesRequestResponse>('requests', {
          method: 'POST',
          body: JSON.stringify(body),
          headers: { 'Content-Type': 'application/json' },
          signal: s,
        }),
    };
