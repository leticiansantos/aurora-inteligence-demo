import {
  MARKET_DEFAULTS,
  MARKET_PERIODS,
  MARKET_SEGMENTS,
  MARKET_VIEWS,
  type ApiErrorBody,
} from '../../shared/market.js';
import type { MarketSegment, MarketPeriod, MarketView } from '../../shared/market.js';

export const BRANDS_LIMIT = { default: 10, max: 25 } as const;
export const MODELS_LIMIT = { default: 10, max: 50 } as const;

export class ParamError extends Error {
  constructor(
    readonly param: string,
    message: string
  ) {
    super(message);
    this.name = 'ParamError';
  }

  toBody(): ApiErrorBody {
    return { error: { code: 'invalid_parameter', message: this.message, param: this.param } };
  }
}

export interface ParsedMarketQuery {
  segment: MarketSegment;
  period: MarketPeriod;
  view: MarketView;
  /** "YYYY-MM-01" or null (= latest). */
  month: string | null;
  /** Only set when the endpoint accepts `limit`. */
  limit: number | null;
}

type RawQuery = Record<string, unknown>;

/** Reads a single non-empty string value; a repeated or non-string param is rejected. */
function single(raw: RawQuery, name: string): string | undefined {
  const value = raw[name];
  if (value === undefined) return undefined;
  if (typeof value !== 'string') throw new ParamError(name, `Parâmetro "${name}" deve ser informado uma única vez.`);
  if (value.length === 0) throw new ParamError(name, `Parâmetro "${name}" não pode ser vazio.`);
  return value;
}

function oneOf<T extends string>(raw: RawQuery, name: string, allowed: readonly T[], fallback: T): T {
  const value = single(raw, name);
  if (value === undefined) return fallback;
  if (!(allowed as readonly string[]).includes(value)) {
    throw new ParamError(name, `Valor inválido para "${name}". Use um de: ${allowed.join(', ')}.`);
  }
  return value as T;
}

/** Accepts "YYYY-MM" or "YYYY-MM-01"; returns "YYYY-MM-01". */
export function normalizeMonth(value: string, name = 'month'): string {
  const match = /^(\d{4})-(0[1-9]|1[0-2])(?:-01)?$/.exec(value);
  if (!match) throw new ParamError(name, `Mês inválido em "${name}". Use o formato AAAA-MM.`);
  return `${match[1]}-${match[2]}-01`;
}

function parseLimit(raw: RawQuery, limits: { default: number; max: number }): number {
  const value = single(raw, 'limit');
  if (value === undefined) return limits.default;
  if (!/^\d+$/.test(value)) throw new ParamError('limit', 'O parâmetro "limit" deve ser um número inteiro.');
  const n = Number(value);
  if (n < 1 || n > limits.max) {
    throw new ParamError('limit', `O parâmetro "limit" deve estar entre 1 e ${limits.max}.`);
  }
  return n;
}

export interface ParseOptions {
  month: boolean;
  limit: { default: number; max: number } | null;
}

export function parseMarketQuery(raw: RawQuery, options: ParseOptions): ParsedMarketQuery {
  const segment = oneOf(raw, 'segment', MARKET_SEGMENTS, MARKET_DEFAULTS.segment);
  const period = oneOf(raw, 'period', MARKET_PERIODS, MARKET_DEFAULTS.period);
  const view = oneOf(raw, 'view', MARKET_VIEWS, MARKET_DEFAULTS.view);
  let month: string | null = null;
  if (options.month) {
    const value = single(raw, 'month');
    month = value === undefined ? null : normalizeMonth(value);
  }
  const limit = options.limit ? parseLimit(raw, options.limit) : null;
  return { segment, period, view, month, limit };
}
