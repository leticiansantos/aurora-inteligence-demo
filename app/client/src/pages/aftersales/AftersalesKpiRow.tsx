import type { ReactNode } from 'react';
import { Skeleton } from '@databricks/appkit-ui/react';
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import type { AftersalesKpi, AftersalesSummaryResponse } from '@/api/aftersales';
import type { Remote } from '@/api/useMarketData';
import { ErrorState } from '@/components/StateViews';
import { formatBrl, formatDays, formatPercent, formatUnits } from '@/lib/format';

function Kpi({
  label,
  value,
  detail,
  attention,
}: {
  label: string;
  value: ReactNode;
  detail: ReactNode;
  attention?: boolean;
}) {
  return (
    <div className={`flex flex-col gap-1 border-l-2 pl-4 ${attention ? 'border-accent' : 'border-border'}`}>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="m-0 font-display text-4xl font-semibold leading-none text-foreground">{value}</dd>
      <dd className="m-0 min-h-5">{detail}</dd>
    </div>
  );
}

/** A KPI the server could not compute (e.g. no demand) arrives null/NaN: show a dash, never "0". */
const known = (n: number | null | undefined): n is number => Number.isFinite(n);
const show = (n: number | null | undefined, format: (n: number) => string) =>
  known(n) ? format(n) : <span aria-label="Sem dado">—</span>;

/** Change vs. the previous window. `goodWhenUp` only picks the wording; the icon stays neutral. */
function Change({ kpi, format }: { kpi: AftersalesKpi; format: (n: number) => string }) {
  if (!known(kpi.value) || !known(kpi.previous))
    return <span className="text-sm text-muted-foreground">sem janela anterior para comparar</span>;
  const diff = kpi.value - kpi.previous;
  const Icon = diff > 0 ? ArrowUpRight : diff < 0 ? ArrowDownRight : Minus;
  return (
    <span className="inline-flex items-center gap-1 text-sm">
      <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
      <span className="font-medium text-foreground">{format(kpi.previous)}</span>
      <span className="text-muted-foreground">na janela anterior</span>
    </span>
  );
}

export function AftersalesKpiRow({
  state,
  onRetry,
}: {
  state: Remote<AftersalesSummaryResponse>;
  onRetry: () => void;
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
  const { kpis, riskDistribution: d, meta } = state.data;
  return (
    <div>
      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-6 lg:grid-cols-4">
        <Kpi
          attention
          label="Peças em risco"
          value={show(kpis.partsAtRisk.value, formatUnits)}
          detail={
            <span className="text-sm text-muted-foreground">
              {formatUnits(d.critical)} críticas e {formatUnits(d.high)} altas (peça × concessionária)
            </span>
          }
        />
        <Kpi
          label="Vendas perdidas evitadas"
          value={show(kpis.lostSalesAvoidedBrl.value, formatBrl)}
          detail={<span className="text-sm text-muted-foreground">se as ações recomendadas forem executadas</span>}
        />
        <Kpi
          label="Taxa de atendimento"
          value={show(kpis.fillRate.value, (n) => formatPercent(n, 1))}
          detail={<Change kpi={kpis.fillRate} format={(n) => formatPercent(n, 1)} />}
        />
        <Kpi
          label="Dias de estoque"
          value={show(kpis.daysOfStock.value, formatDays)}
          detail={<Change kpi={kpis.daysOfStock} format={formatDays} />}
        />
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">
        Horizonte de {meta.query.horizon} dias a partir de {meta.forecastDate.split('-').reverse().join('/')}. Dados
        sintéticos da Aurora Motors, fictícia; modelo {meta.modelVersion}.
      </p>
    </div>
  );
}
