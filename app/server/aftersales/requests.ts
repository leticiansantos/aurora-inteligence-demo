import {
  AFTERSALES_DEFAULT_HORIZON,
  AFTERSALES_HORIZONS,
  AFTERSALES_REQUEST_STATUSES,
  type AftersalesHorizon,
  type AftersalesRiskLevel,
  AFTERSALES_REQUEST_TYPES,
  type AftersalesRequest,
  type AftersalesRequestListQuery,
  type AftersalesRequestStatus,
  type AftersalesRequestType,
  type CreateAftersalesRequestBody,
} from '../../shared/aftersales.js';
import { ApiError, invalid } from './errors.js';
import { text } from './util.js';

/** Postgres schema names (overridable for isolated local tests; plain identifiers only). */
function schemaFromEnv(name: string, fallback: string): string {
  const v = process.env[name]?.trim() || fallback;
  if (!/^[a-z_][a-z0-9_]*$/.test(v)) throw new Error(`${name} must be a plain lowercase identifier`);
  return v;
}
export const REQUESTS_SCHEMA = schemaFromEnv('AFTERSALES_APP_SCHEMA', 'aftersales_app');
export const SYNCED_SCHEMA = schemaFromEnv('AFTERSALES_SYNCED_SCHEMA', 'auto_intelligence');
export const REQUESTS_TABLE = `${REQUESTS_SCHEMA}.aftersales_replenishment_requests`;
const SYNCED = SYNCED_SCHEMA;
export const MAX_QUANTITY = 100_000;
export const MAX_NOTE = 500;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ALLOWED_FIELDS = ['dealerId', 'partId', 'type', 'quantity', 'fromDealerId', 'horizonDays', 'note'] as const;
// Control characters (C0, DEL, C1) are rejected; emoji and accents are fine.
// eslint-disable-next-line no-control-regex
const CONTROL_RE = /[\u0000-\u001f\u007f-\u009f]/;

/** Idempotent DDL, run once at startup by the app service principal (it must own the schema). */
export const REQUESTS_DDL = [
  `CREATE SCHEMA IF NOT EXISTS ${REQUESTS_SCHEMA}`,
  `CREATE TABLE IF NOT EXISTS ${REQUESTS_TABLE} (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dealer_id     text NOT NULL,
    part_id       text NOT NULL,
    type          text NOT NULL CHECK (type IN ('reorder','transfer')),
    quantity      integer NOT NULL CHECK (quantity BETWEEN 1 AND ${MAX_QUANTITY}),
    from_dealer_id text,
    horizon_days  smallint CHECK (horizon_days IN (14,28,56)),
    risk_level    text,
    lost_sales_brl numeric(14,2),
    forecast_date date,
    note          text CHECK (note IS NULL OR char_length(note) <= ${MAX_NOTE}),
    status        text NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open','approved','in_transit','fulfilled','cancelled')),
    requested_by  text NOT NULL DEFAULT 'app',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CHECK ((type = 'transfer') = (from_dealer_id IS NOT NULL)),
    CHECK (from_dealer_id IS NULL OR from_dealer_id <> dealer_id)
  )`,
  // One active request per dealer x part x type, enforced race-free by the database.
  `CREATE UNIQUE INDEX IF NOT EXISTS aftersales_requests_one_active
     ON ${REQUESTS_TABLE} (dealer_id, part_id, type) WHERE status IN ('open','approved','in_transit')`,
  `COMMENT ON TABLE ${REQUESTS_TABLE} IS 'Synthetic demo: replenishment/transfer requests written by the app (Lakebase OLTP).'`,
];

export interface Queryable {
  query(text: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
}

/** Risk-table snapshot of one dealer x part at one horizon (what the screen showed). */
export interface RiskSnapshot {
  /** On-hand units (donor check for transfers). */
  stockUnits: number;
  riskLevel: AftersalesRiskLevel;
  lostSalesBrl: number;
  forecastDate: string;
}

/** Looks up reference data (synced tables in prod, a fake in tests). */
export interface Catalog {
  dealerExists(dealerId: string): Promise<boolean>;
  partExists(partId: string): Promise<boolean>;
  /** Risk row for dealer x part x horizon, or null when the dealer does not carry the part. */
  riskSnapshot(dealerId: string, partId: string, horizon: AftersalesHorizon): Promise<RiskSnapshot | null>;
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

const requiredId = (body: Record<string, unknown>, field: string): string => {
  const v = body[field];
  if (typeof v !== 'string' || v.trim().length === 0 || v.length > 64 || CONTROL_RE.test(v)) {
    throw invalid(field, `Campo "${field}" é obrigatório e deve ser um identificador válido.`);
  }
  return v;
};

/** Pure shape validation (no I/O). Business checks that need the catalog happen in `validateAgainstCatalog`. */
export function parseCreateBody(raw: unknown): CreateAftersalesRequestBody {
  if (!isObject(raw)) throw invalid('body', 'O corpo da requisição deve ser um objeto JSON.');
  for (const key of Object.keys(raw)) {
    if (!(ALLOWED_FIELDS as readonly string[]).includes(key)) throw invalid(key, `Campo desconhecido: "${key}".`);
  }
  const dealerId = requiredId(raw, 'dealerId');
  const partId = requiredId(raw, 'partId');
  const type = raw.type;
  if (typeof type !== 'string' || !(AFTERSALES_REQUEST_TYPES as readonly string[]).includes(type)) {
    throw invalid('type', `Campo "type" deve ser um de: ${AFTERSALES_REQUEST_TYPES.join(', ')}.`);
  }
  const quantity = raw.quantity;
  if (typeof quantity !== 'number' || !Number.isInteger(quantity) || quantity < 1 || quantity > MAX_QUANTITY) {
    throw invalid('quantity', `Campo "quantity" deve ser um número inteiro entre 1 e ${MAX_QUANTITY}.`);
  }
  let fromDealerId: string | undefined;
  if (raw.fromDealerId !== undefined) {
    if (type === 'reorder') throw invalid('fromDealerId', 'Reposição não aceita loja de origem.');
    fromDealerId = requiredId(raw, 'fromDealerId');
  }
  if (type === 'transfer') {
    if (fromDealerId === undefined) throw invalid('fromDealerId', 'Transferência exige a loja de origem.');
    if (fromDealerId === dealerId) throw invalid('fromDealerId', 'A loja de origem deve ser diferente do destino.');
  }
  let horizonDays: AftersalesHorizon | undefined;
  if (raw.horizonDays !== undefined) {
    if (!(AFTERSALES_HORIZONS as readonly unknown[]).includes(raw.horizonDays)) {
      throw invalid('horizonDays', `Campo "horizonDays" deve ser um de: ${AFTERSALES_HORIZONS.join(', ')}.`);
    }
    horizonDays = raw.horizonDays as AftersalesHorizon;
  }
  let note: string | undefined;
  if (raw.note !== undefined && raw.note !== null) {
    if (typeof raw.note !== 'string') throw invalid('note', 'Campo "note" deve ser texto.');
    const trimmed = raw.note.trim();
    if ([...trimmed].length > MAX_NOTE) throw invalid('note', `Campo "note" aceita até ${MAX_NOTE} caracteres.`);
    // Newlines/tabs are control characters too: notes are single-line.
    if (CONTROL_RE.test(trimmed)) throw invalid('note', 'Campo "note" contém caracteres inválidos.');
    note = trimmed.length > 0 ? trimmed : undefined;
  }
  return { dealerId, partId, type: type as AftersalesRequestType, quantity, fromDealerId, horizonDays, note };
}

export interface ValidatedRequest extends CreateAftersalesRequestBody {
  horizonDays: AftersalesHorizon;
  snapshot: RiskSnapshot;
}

export async function validateAgainstCatalog(
  body: CreateAftersalesRequestBody,
  catalog: Catalog
): Promise<ValidatedRequest> {
  const horizonDays = body.horizonDays ?? AFTERSALES_DEFAULT_HORIZON;
  if (!(await catalog.dealerExists(body.dealerId))) throw invalid('dealerId', 'Loja desconhecida.');
  if (!(await catalog.partExists(body.partId))) throw invalid('partId', 'Peça desconhecida.');
  const snapshot = await catalog.riskSnapshot(body.dealerId, body.partId, horizonDays);
  if (!snapshot) throw invalid('partId', 'Esta loja não trabalha com a peça informada.');
  if (body.type === 'transfer' && body.fromDealerId) {
    if (!(await catalog.dealerExists(body.fromDealerId))) throw invalid('fromDealerId', 'Loja de origem desconhecida.');
    const donor = await catalog.riskSnapshot(body.fromDealerId, body.partId, horizonDays);
    if (!donor) throw invalid('fromDealerId', 'A loja de origem não trabalha com a peça informada.');
    if (body.quantity > donor.stockUnits) {
      throw invalid('quantity', `A loja de origem tem apenas ${donor.stockUnits} unidade(s) em estoque.`);
    }
  }
  return { ...body, horizonDays, snapshot };
}

export function parseRequestId(id: unknown): string {
  if (typeof id !== 'string' || !UUID_RE.test(id)) throw invalid('id', 'Identificador de pedido inválido.');
  return id.toLowerCase();
}

export function parseListQuery(
  raw: Record<string, unknown>
): Required<Pick<AftersalesRequestListQuery, 'limit'>> & Omit<AftersalesRequestListQuery, 'limit'> {
  const one = (name: string): string | undefined => {
    const v = raw[name];
    if (v === undefined) return undefined;
    if (typeof v !== 'string' || v.length === 0) throw invalid(name, `Parâmetro "${name}" inválido.`);
    return v;
  };
  const status = one('status');
  if (status !== undefined && !(AFTERSALES_REQUEST_STATUSES as readonly string[]).includes(status)) {
    throw invalid('status', `Valor inválido para "status". Use um de: ${AFTERSALES_REQUEST_STATUSES.join(', ')}.`);
  }
  const limitRaw = one('limit');
  let limit = 20;
  if (limitRaw !== undefined) {
    if (!/^(0|[1-9]\d*)$/.test(limitRaw) || Number(limitRaw) < 1 || Number(limitRaw) > 100) {
      throw invalid('limit', 'Parâmetro "limit" deve ser um inteiro entre 1 e 100.');
    }
    limit = Number(limitRaw);
  }
  return { status: status as AftersalesRequestStatus | undefined, dealer: one('dealer'), limit };
}

// Names come from the synced dealer/part tables at read time (nothing denormalized except the snapshot).
const SELECT = `SELECT r.id, r.dealer_id, coalesce(d.dealer_name, r.dealer_id) AS dealer_name, r.part_id,
  coalesce(p.part_name, r.part_id) AS part_name, r.type, r.quantity,
  r.from_dealer_id, r.note, r.horizon_days, r.risk_level, r.lost_sales_brl, r.forecast_date,
  r.status, r.requested_by, r.created_at, r.updated_at`;
const JOINS = `LEFT JOIN ${SYNCED}.aftersales_lb_dealers d ON d.dealer_id = r.dealer_id
  LEFT JOIN ${SYNCED}.aftersales_lb_parts p ON p.part_id = r.part_id`;

const iso = (v: unknown): string => (v instanceof Date ? v.toISOString() : text(v));
const dateOnly = (v: unknown): string | null =>
  v === null || v === undefined ? null : v instanceof Date ? v.toISOString().slice(0, 10) : text(v).slice(0, 10);
const nullable = (v: unknown): string | null => (v === null || v === undefined ? null : text(v));

export function toRequest(row: Record<string, unknown>): AftersalesRequest {
  return {
    id: text(row.id),
    dealerId: text(row.dealer_id),
    dealerName: text(row.dealer_name),
    partId: text(row.part_id),
    partName: text(row.part_name),
    type: row.type as AftersalesRequestType,
    quantity: Number(row.quantity),
    fromDealerId: nullable(row.from_dealer_id),
    note: nullable(row.note),
    horizonDays:
      row.horizon_days === null || row.horizon_days === undefined
        ? null
        : (Number(row.horizon_days) as AftersalesHorizon),
    riskLevel: nullable(row.risk_level) as AftersalesRiskLevel | null,
    lostSalesBrl: row.lost_sales_brl === null || row.lost_sales_brl === undefined ? null : Number(row.lost_sales_brl),
    forecastDate: dateOnly(row.forecast_date),
    status: row.status as AftersalesRequestStatus,
    createdAt: iso(row.created_at),
    updatedAt: iso(row.updated_at),
    requestedBy: text(row.requested_by),
  };
}

export class RequestRepository {
  constructor(private readonly db: Queryable) {}

  private ready: Promise<void> | null = null;

  /** Idempotent DDL. Safe to call repeatedly; a failure is not cached, so the next call retries. */
  init(): Promise<void> {
    this.ready ??= (async () => {
      for (const stmt of REQUESTS_DDL) await this.db.query(stmt);
    })().catch((err: unknown) => {
      this.ready = null;
      throw err;
    });
    return this.ready;
  }

  async create(v: ValidatedRequest, requestedBy: string): Promise<AftersalesRequest> {
    await this.init();
    try {
      const { rows } = await this.db.query(
        `WITH r AS (
           INSERT INTO ${REQUESTS_TABLE}
             (dealer_id, part_id, type, quantity, from_dealer_id, note, horizon_days, risk_level,
              lost_sales_brl, forecast_date, requested_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *)
         ${SELECT} FROM r ${JOINS}`,
        [
          v.dealerId,
          v.partId,
          v.type,
          v.quantity,
          v.fromDealerId ?? null,
          v.note ?? null,
          v.horizonDays,
          v.snapshot.riskLevel,
          v.snapshot.lostSalesBrl,
          v.snapshot.forecastDate,
          requestedBy,
        ]
      );
      return toRequest(rows[0]);
    } catch (err) {
      if ((err as { code?: string }).code === '23505') {
        throw new ApiError(409, 'duplicate_request', 'Já existe um pedido ativo para esta loja, peça e tipo.');
      }
      throw err;
    }
  }

  async get(id: string): Promise<AftersalesRequest> {
    await this.init();
    const { rows } = await this.db.query(`${SELECT} FROM ${REQUESTS_TABLE} r ${JOINS} WHERE r.id = $1`, [id]);
    if (rows.length === 0) throw new ApiError(404, 'not_found', 'Pedido não encontrado.');
    return toRequest(rows[0]);
  }

  async list(q: ReturnType<typeof parseListQuery>): Promise<AftersalesRequest[]> {
    await this.init();
    const { rows } = await this.db.query(
      `${SELECT} FROM ${REQUESTS_TABLE} r ${JOINS}
       WHERE ($1::text IS NULL OR r.status = $1) AND ($2::text IS NULL OR r.dealer_id = $2)
       ORDER BY r.created_at DESC, r.id LIMIT $3`,
      [q.status ?? null, q.dealer ?? null, q.limit]
    );
    return rows.map(toRequest);
  }

  /** Latest active request per "dealer:part" key, for the risk ranking's `openRequest`. */
  async activeByKey(keys: { dealerId: string; partId: string }[]) {
    if (keys.length === 0)
      return new Map<string, { id: string; status: AftersalesRequestStatus; type: AftersalesRequestType }>();
    // Deliberately no init(): reading open requests must not depend on the OLTP migration (see service.risk).
    const { rows } = await this.db.query(
      `SELECT DISTINCT ON (dealer_id, part_id) dealer_id, part_id, id, status, type
       FROM ${REQUESTS_TABLE}
       WHERE status IN ('open','approved','in_transit') AND (dealer_id, part_id) IN (
         SELECT * FROM unnest($1::text[], $2::text[]))
       ORDER BY dealer_id, part_id, created_at DESC`,
      [keys.map((k) => k.dealerId), keys.map((k) => k.partId)]
    );
    return new Map(
      rows.map((r) => [
        `${text(r.dealer_id)}:${text(r.part_id)}`,
        { id: text(r.id), status: r.status as AftersalesRequestStatus, type: r.type as AftersalesRequestType },
      ])
    );
  }
}
