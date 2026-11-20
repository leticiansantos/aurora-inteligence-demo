import type { MarketPeriod, MarketSegment, MarketView } from '@/api/market';

export const SEGMENT_OPTIONS: { value: MarketSegment; label: string }[] = [
  { value: 'total', label: 'Total' },
  { value: 'automoveis', label: 'Automóveis' },
  { value: 'comerciais_leves', label: 'Comerciais leves' },
];
export const PERIOD_OPTIONS: { value: MarketPeriod; label: string; long: string }[] = [
  { value: '12m', label: '12 meses', long: 'últimos 12 meses' },
  { value: '24m', label: '24 meses', long: 'últimos 24 meses' },
  { value: '60m', label: '5 anos', long: 'últimos 5 anos' },
  { value: 'all', label: 'Tudo', long: 'todo o histórico' },
];
export const VIEW_OPTIONS: { value: MarketView; label: string }[] = [
  { value: 'with_aurora', label: 'Com a Aurora' },
  { value: 'real', label: 'Só mercado real' },
];

export const segmentLabel = (s: MarketSegment) => SEGMENT_OPTIONS.find((o) => o.value === s)?.label ?? s;
export const periodLong = (p: MarketPeriod) => PERIOD_OPTIONS.find((o) => o.value === p)?.long ?? p;

/** Why Aurora numbers are absent for a selection (null when they should be present). */
export function auroraAbsenceReason(segment: MarketSegment, view: MarketView): string | null {
  if (view === 'real') return 'Visão “Só mercado real”: a Aurora Motors não entra na conta.';
  if (segment === 'comerciais_leves') return 'A Aurora Motors não atua em comerciais leves.';
  return null;
}
