import type {
  AftersalesAction,
  AftersalesHorizon,
  AftersalesRequestStatus,
  AftersalesRequestType,
  AftersalesRiskLevel,
} from '@/api/aftersales';

export const RISK_LABEL: Record<AftersalesRiskLevel, string> = {
  critical: 'Crítico',
  high: 'Alto',
  medium: 'Médio',
  low: 'Baixo',
};
export const ACTION_LABEL: Record<AftersalesAction, string> = {
  reorder: 'Repor estoque',
  transfer: 'Transferir de outra concessionária',
  monitor: 'Acompanhar',
};
export const REQUEST_TYPE_LABEL: Record<AftersalesRequestType, string> = {
  reorder: 'Reposição',
  transfer: 'Transferência',
};
export const STATUS_LABEL: Record<AftersalesRequestStatus, string> = {
  open: 'Aberto',
  approved: 'Aprovado',
  in_transit: 'Em trânsito',
  fulfilled: 'Atendido',
  cancelled: 'Cancelado',
};
export const horizonLabel = (h: AftersalesHorizon) => `${h} dias`;

/** Amber is reserved for attention: only critical and high risk use it. */
export const isAttention = (l: AftersalesRiskLevel) => l === 'critical' || l === 'high';

/** A transfer needs a donor dealer; without `transferFrom` the recommendation degrades to a reorder. */
export const effectiveAction = (r: { action: AftersalesAction; transferFrom: unknown }): AftersalesAction =>
  r.action === 'transfer' && !r.transferFrom ? 'reorder' : r.action;
