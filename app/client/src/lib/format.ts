const NF = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
const NF_COMPACT = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 });
const MONTH_SHORT = new Intl.DateTimeFormat('pt-BR', { month: 'short', year: '2-digit', timeZone: 'UTC' });
const MONTH_LONG = new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' });

/** 1234567 -> "1.234.567" */
export const formatUnits = (n: number): string => NF.format(n);
export const formatCompact = (n: number): string => NF_COMPACT.format(n);

/** Fraction to percent: 0.034 -> "3,4%". Signed variant adds "+" for positives. */
export function formatPercent(fraction: number, digits = 1, signed = false): string {
  const s = new Intl.NumberFormat('pt-BR', {
    style: 'percent',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    signDisplay: signed ? 'exceptZero' : 'auto',
  }).format(fraction);
  return s.replace(/\s/g, '');
}

/** Fraction to percentage points: 0.004 -> "+0,4 p.p." */
export function formatPp(fraction: number): string {
  const s = new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    signDisplay: 'exceptZero',
  }).format(fraction * 100);
  return `${s} p.p.`;
}

const parse = (iso: string) => new Date(`${iso.slice(0, 7)}-01T00:00:00Z`);
/** "2026-09-01" -> "set/26" */
export const formatMonthShort = (iso: string): string =>
  MONTH_SHORT.format(parse(iso))
    .replace(/\.?\s+de\s+/, '/')
    .replace(/\.?\s+/, '/');
/** "2026-09-01" -> "setembro de 2026" */
export const formatMonthLong = (iso: string): string => MONTH_LONG.format(parse(iso));

const BRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });
const DEC1 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
/** 1234.5 -> "R$ 1.235" */
export const formatBrl = (n: number): string => BRL.format(n);
/** 12.34 -> "12,3 dias" */
export const formatDays = (n: number): string => `${DEC1.format(n)} dias`;
