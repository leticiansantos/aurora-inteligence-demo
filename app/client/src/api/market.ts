import type {
  ApiErrorBody,
  MarketBrandsResponse,
  MarketLimitQuery,
  MarketModelsResponse,
  MarketQuery,
  MarketSummaryResponse,
  MarketTimeseriesResponse,
} from '../../../shared/market';
import { mockMarket } from './marketMock';

export type * from '../../../shared/market';
export { MARKET_DEFAULTS } from '../../../shared/market';

/** Set VITE_MARKET_MOCK=1 to render the page from typed mock data (no server needed). */
const USE_MOCK = import.meta.env.VITE_MARKET_MOCK === '1';

export class MarketApiError extends Error {
  readonly status: number;
  readonly code?: ApiErrorBody['error']['code'];
  constructor(message: string, status: number, code?: ApiErrorBody['error']['code']) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** pt-BR copy owned by the client; server text is never shown (it is for logs and tests). */
function errorCopy(status: number): string {
  if (status === 400) return 'Os filtros escolhidos não são válidos. Ajuste a seleção e tente novamente.';
  if (status === 503) return 'O serviço de dados está indisponível no momento. Tente novamente em instantes.';
  return 'Não foi possível carregar os dados de mercado. Tente novamente.';
}

async function get<T>(path: string, query: MarketLimitQuery, signal?: AbortSignal): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined) qs.set(k, String(v));
  let res: Response;
  try {
    res = await fetch(`/api/market/${path}?${qs}`, { signal, headers: { Accept: 'application/json' } });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new MarketApiError('Não foi possível conectar ao servidor. Verifique a conexão e tente novamente.', 0);
  }
  const isJson = (res.headers.get('content-type') ?? '').includes('application/json');
  if (!res.ok) {
    const body = isJson ? ((await res.json().catch(() => null)) as ApiErrorBody | null) : null;
    throw new MarketApiError(errorCopy(res.status), res.status, body?.error.code);
  }
  if (!isJson) throw new MarketApiError(errorCopy(res.status), res.status);
  return (await res.json()) as T;
}

export const marketApi = USE_MOCK
  ? mockMarket
  : {
      summary: (q: MarketQuery, s?: AbortSignal) => get<MarketSummaryResponse>('summary', q, s),
      timeseries: (q: MarketQuery, s?: AbortSignal) => get<MarketTimeseriesResponse>('timeseries', q, s),
      brands: (q: MarketLimitQuery, s?: AbortSignal) => get<MarketBrandsResponse>('brands', q, s),
      models: (q: MarketLimitQuery, s?: AbortSignal) => get<MarketModelsResponse>('models', q, s),
    };
