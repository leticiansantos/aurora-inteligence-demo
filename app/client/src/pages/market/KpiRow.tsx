import type { ReactNode } from 'react';
import { Skeleton } from '@databricks/appkit-ui/react';
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import type { MarketSummaryResponse } from '@/api/market';
import { formatMonthLong, formatMonthShort, formatPercent, formatPp, formatUnits } from '@/lib/format';
import { ErrorState } from '@/components/StateViews';
import type { Remote } from '@/api/useMarketData';

function Delta({ value, text, suffix }: { value: number | null; text: string; suffix: string }) {
  if (value === null) return <span className="text-sm text-muted-foreground">{suffix}</span>;
  const Icon = value > 0 ? ArrowUpRight : value < 0 ? ArrowDownRight : Minus;
  return (
    <span className="inline-flex items-center gap-1 text-sm text-foreground">
      <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
      <span className="font-medium">{text}</span>
      <span className="text-muted-foreground">{suffix}</span>
    </span>
  );
}

function Kpi({ label, value, detail, muted }: { label: string; value: ReactNode; detail: ReactNode; muted?: boolean }) {
  return (
    <div className="flex flex-col gap-1 border-l-2 border-border pl-4">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd
        className={`m-0 font-display text-4xl font-semibold leading-none ${muted ? 'text-muted-foreground' : 'text-foreground'}`}
      >
        {value}
      </dd>
      <dd className="m-0 min-h-5">{detail}</dd>
    </div>
  );
}

export function KpiRow({
  state,
  onRetry,
  absence,
}: {
  state: Remote<MarketSummaryResponse>;
  onRetry: () => void;
  absence: string | null;
}) {
  if (state.phase === 'error')
    return <ErrorState title="Não foi possível carregar os indicadores" message={state.message} onRetry={onRetry} />;
  if (state.phase === 'loading')
    return (
      <div role="status" aria-live="polite" className="grid grid-cols-2 gap-6 lg:grid-cols-4">
        <span className="sr-only">Carregando indicadores…</span>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="space-y-2 border-l-2 border-border pl-4">
            <Skeleton className="bg-muted h-3 w-24" />
            <Skeleton className="bg-muted h-9 w-32" />
            <Skeleton className="bg-muted h-4 w-28" />
          </div>
        ))}
      </div>
    );

  const { market, aurora, month, previousYearMonth } = state.data;
  // The YoY compares the total of the selected view: say whether Aurora is in it.
  const { view, segment } = state.data.meta.query;
  const basis = view === 'with_aurora' && segment !== 'comerciais_leves' ? 'com a Aurora' : 'mercado real';
  const monthText = formatMonthLong(month);
  const none = <span aria-label="Sem dado">—</span>;
  return (
    <div>
      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-6 lg:grid-cols-4">
        <Kpi
          label={`Mercado em ${formatMonthShort(month)}`}
          value={formatUnits(market.totalUnits)}
          detail={
            <span className="text-sm text-muted-foreground">
              emplacamentos em {monthText}, {basis}
            </span>
          }
        />
        <Kpi
          label={`Variação anual (${basis})`}
          value={market.yoyPct === null ? none : formatPercent(market.yoyPct, 1, true)}
          detail={
            <Delta
              value={market.yoyPct}
              text={market.previousYearUnits === null ? '' : formatUnits(market.previousYearUnits)}
              suffix={
                market.previousYearUnits === null
                  ? 'sem dado do ano anterior'
                  : `vs. mesmo mês de ${previousYearMonth.slice(0, 4)}`
              }
            />
          }
        />
        <Kpi
          label="Participação da Aurora"
          muted={!aurora}
          value={aurora ? formatPercent(aurora.share, 1) : none}
          detail={
            aurora ? (
              <Delta
                value={aurora.shareChangePp}
                text={aurora.shareChangePp === null ? '' : formatPp(aurora.shareChangePp)}
                suffix={aurora.shareChangePp === null ? 'Aurora ainda não existia há um ano' : 'vs. ano anterior'}
              />
            ) : (
              <span className="text-sm text-muted-foreground">sem dado nesta seleção</span>
            )
          }
        />
        <Kpi
          label="Posição da Aurora"
          muted={!aurora || aurora.rank === null}
          value={aurora && aurora.rank !== null ? `${aurora.rank}º` : none}
          detail={
            <span className="text-sm text-muted-foreground">
              {aurora && aurora.rank !== null ? `entre ${aurora.rankedBrands} marcas` : 'sem dado nesta seleção'}
            </span>
          }
        />
      </dl>
      {absence && <p className="mt-3 text-sm text-muted-foreground">{absence}</p>}
      <p className="mt-3 text-xs text-muted-foreground">
        Fonte: emplacamentos mensais publicados pela Fenabrave. Dados de{' '}
        {formatMonthShort(state.data.coverage.firstMonth)} a {formatMonthShort(state.data.coverage.lastMonth)} (
        {state.data.coverage.monthsCount} meses). A Aurora Motors é uma marca fictícia, com dados sintéticos somados ao
        mercado real.
      </p>
    </div>
  );
}
