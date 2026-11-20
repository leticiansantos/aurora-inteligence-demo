import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  ToggleGroup,
  ToggleGroupItem,
} from '@databricks/appkit-ui/react';
import type { MarketPeriod, MarketQuery, MarketSegment, MarketView } from '@/api/market';
import { PERIOD_OPTIONS, SEGMENT_OPTIONS, VIEW_OPTIONS } from './labels';

export type MarketFilterState = Required<Omit<MarketQuery, 'month'>> & { month: string | null };
type Required3 = MarketFilterState;

function Group<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span id={`flt-${label}`} className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={value}
        aria-labelledby={`flt-${label}`}
        // Radix emits "" when the active item is clicked again: keep the selection.
        onValueChange={(v) => v && onChange(v as T)}
      >
        {options.map((o) => (
          <ToggleGroupItem
            key={o.value}
            value={o.value}
            className="px-3 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          >
            {o.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}

export function MarketFilters({
  query,
  onChange,
  coverage,
}: {
  query: Required3;
  onChange: (q: Required3) => void;
  coverage: { firstMonth: string; lastMonth: string } | null;
}) {
  return (
    <div
      role="group"
      aria-label="Filtros"
      className="flex flex-wrap items-end gap-x-8 gap-y-4 border-y bg-card/60 px-1 py-4"
    >
      <Group<MarketSegment>
        label="Segmento"
        value={query.segment}
        options={SEGMENT_OPTIONS}
        onChange={(segment) => onChange({ ...query, segment })}
      />
      <Group<MarketPeriod>
        label="Período"
        value={query.period}
        options={PERIOD_OPTIONS}
        onChange={(period) => onChange({ ...query, period })}
      />
      <Group<MarketView>
        label="Visão"
        value={query.view}
        options={VIEW_OPTIONS}
        onChange={(view) => onChange({ ...query, view })}
      />
      <MonthPicker query={query} onChange={onChange} coverage={coverage} />
    </div>
  );
}

const MONTH_NAMES = [
  'janeiro',
  'fevereiro',
  'março',
  'abril',
  'maio',
  'junho',
  'julho',
  'agosto',
  'setembro',
  'outubro',
  'novembro',
  'dezembro',
];

/** Month + year selects (pt-BR labels, clamped to the loaded coverage); "Mais recente" clears the choice. */
function MonthPicker({
  query,
  onChange,
  coverage,
}: {
  query: Required3;
  onChange: (q: Required3) => void;
  coverage: { firstMonth: string; lastMonth: string } | null;
}) {
  const latest = coverage?.lastMonth.slice(0, 7) ?? null;
  const current = query.month ?? latest;
  const [year, month] = current ? current.split('-').map(Number) : [0, 0];
  const firstY = coverage ? Number(coverage.firstMonth.slice(0, 4)) : year;
  const lastY = coverage ? Number(coverage.lastMonth.slice(0, 4)) : year;
  const years = Array.from({ length: Math.max(0, lastY - firstY + 1) }, (_, i) => lastY - i);

  const clamp = (y: number, m: number): string | null => {
    if (!coverage) return null;
    let v = `${y}-${String(m).padStart(2, '0')}`;
    if (v < coverage.firstMonth.slice(0, 7)) v = coverage.firstMonth.slice(0, 7);
    if (v > coverage.lastMonth.slice(0, 7)) v = coverage.lastMonth.slice(0, 7);
    return v;
  };
  const commit = (v: string | null) => v && onChange({ ...query, month: v === latest ? null : v });

  return (
    <div className="flex flex-col gap-1.5">
      <span id="flt-month" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Mês de referência
      </span>
      <div className="flex items-center gap-2" role="group" aria-labelledby="flt-month">
        <Select
          value={current ? String(month) : ''}
          disabled={!coverage}
          onValueChange={(m) => commit(clamp(year, Number(m)))}
        >
          <SelectTrigger size="sm" className="w-[8.5rem]" aria-label="Mês">
            <SelectValue placeholder="Mês" />
          </SelectTrigger>
          <SelectContent>
            {MONTH_NAMES.map((n, i) => (
              <SelectItem key={n} value={String(i + 1)}>
                {n.charAt(0).toUpperCase() + n.slice(1)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={current ? String(year) : ''}
          disabled={!coverage}
          onValueChange={(y) => commit(clamp(Number(y), month))}
        >
          <SelectTrigger size="sm" className="w-[5.5rem]" aria-label="Ano">
            <SelectValue placeholder="Ano" />
          </SelectTrigger>
          <SelectContent>
            {years.map((y) => (
              <SelectItem key={y} value={String(y)}>
                {y}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {query.month && (
          <button
            type="button"
            className="text-sm text-primary underline underline-offset-2"
            onClick={() => onChange({ ...query, month: null })}
          >
            Mais recente
          </button>
        )}
      </div>
    </div>
  );
}
