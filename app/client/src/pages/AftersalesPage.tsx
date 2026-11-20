import { useCallback, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { Alert, AlertDescription, AlertTitle } from '@databricks/appkit-ui/react';
import { CheckCircle2 } from 'lucide-react';
import { AFTERSALES_DEFAULT_HORIZON, AFTERSALES_HORIZONS, aftersalesApi } from '@/api/aftersales';
import type { AftersalesHorizon, AftersalesQuery, AftersalesRequest, AftersalesRiskRow } from '@/api/aftersales';
import { useRemote } from '@/api/useMarketData';
import { ErrorState } from '@/components/StateViews';
import { formatUnits } from '@/lib/format';
import { AftersalesFilters, type AftersalesFilterState } from './aftersales/AftersalesFilters';
import { AftersalesKpiRow } from './aftersales/AftersalesKpiRow';
import { ForecastCard } from './aftersales/ForecastCard';
import { RequestDialog } from './aftersales/RequestDialog';
import { RequestsCard } from './aftersales/RequestsCard';
import { RiskTable } from './aftersales/RiskTable';
import { REQUEST_TYPE_LABEL } from './aftersales/labels';

const ID = /^[A-Za-z0-9_-]{1,40}$/;

/** Filters live in the URL (?concessionaria=&categoria=&horizonte=&risco=) so a view can be shared and reloaded. */
function useFilters(): [AftersalesFilterState, (f: AftersalesFilterState) => void] {
  const [params, setParams] = useSearchParams();
  const filters = useMemo<AftersalesFilterState>(() => {
    const dealer = params.get('concessionaria');
    const category = params.get('categoria');
    const horizon = Number(params.get('horizonte'));
    return {
      dealer: dealer && ID.test(dealer) ? dealer : 'all',
      category: category && ID.test(category) ? category : 'all',
      horizon: (AFTERSALES_HORIZONS as readonly number[]).includes(horizon)
        ? (horizon as AftersalesHorizon)
        : AFTERSALES_DEFAULT_HORIZON,
      onlyHigh: params.get('risco') === 'alto',
    };
  }, [params]);
  const set = useCallback(
    (f: AftersalesFilterState) => {
      const next = new URLSearchParams();
      if (f.dealer !== 'all') next.set('concessionaria', f.dealer);
      if (f.category !== 'all') next.set('categoria', f.category);
      if (f.horizon !== AFTERSALES_DEFAULT_HORIZON) next.set('horizonte', String(f.horizon));
      if (f.onlyHigh) next.set('risco', 'alto');
      const mock = params.get('mock');
      if (mock) next.set('mock', mock);
      setParams(next, { replace: true });
    },
    [params, setParams]
  );
  return [filters, set];
}

export function AftersalesPage({ title, description }: { title: string; description: string }) {
  const [filters, setFiltersRaw] = useFilters();
  const q: AftersalesQuery = useMemo(
    () => ({
      ...(filters.dealer !== 'all' ? { dealer: filters.dealer } : {}),
      ...(filters.category !== 'all' ? { category: filters.category } : {}),
      horizon: filters.horizon,
    }),
    [filters]
  );
  const key = `${filters.dealer}|${filters.category}|${filters.horizon}`;

  const options = useRemote((s) => aftersalesApi.filters(s), 'filters');
  const summary = useRemote((s) => aftersalesApi.summary(q, s), key);
  // The series ignores the horizon (26 real weeks + backtest + 8 future weeks): no refetch when it changes.
  const { horizon: _h, ...qNoHorizon } = q;
  const forecast = useRemote((s) => aftersalesApi.forecast(qNoHorizon, s), `${filters.dealer}|${filters.category}`);
  const risk = useRemote(
    (s) => aftersalesApi.risk({ ...q, limit: 50, ...(filters.onlyHigh ? { minLevel: 'high' as const } : {}) }, s),
    `${key}|${filters.onlyHigh}`
  );
  const requests = useRemote((s) => aftersalesApi.requests({ limit: 10 }, s), 'requests');

  const [target, setTarget] = useState<AftersalesRiskRow | null>(null);
  const [created, setCreated] = useState<AftersalesRequest | null>(null);

  // The confirmation is about the previous selection: drop it when the filters change.
  const setFilters = (f: AftersalesFilterState) => {
    setCreated(null);
    setFiltersRaw(f);
  };

  const refreshAfterWrite = () => {
    risk.retry();
    requests.retry();
  };

  const onCreated = (r: AftersalesRequest) => {
    setTarget(null);
    setCreated(r);
    // Re-read the ranking (row now shows its request) and the request list.
    risk.retry();
    requests.retry();
  };

  return (
    <section aria-labelledby="section-title" className="mx-auto max-w-6xl space-y-8">
      <header>
        <h2 id="section-title" className="font-display text-3xl font-semibold text-foreground">
          {title}
        </h2>
        <p className="mt-1 max-w-[65ch] text-muted-foreground">{description}</p>
      </header>
      <AftersalesFilters
        value={filters}
        onChange={setFilters}
        options={options.state.phase === 'ready' ? options.state.data : options.lastData}
      />
      {options.state.phase === 'error' && (
        <ErrorState
          title="Não foi possível carregar as opções de filtro"
          message={options.state.message}
          onRetry={options.retry}
        />
      )}
      <AftersalesKpiRow state={summary.state} onRetry={summary.retry} />
      <ForecastCard state={forecast.state} onRetry={forecast.retry} />
      {created && (
        <Alert role="status">
          <CheckCircle2 className="h-4 w-4" />
          <AlertTitle>Pedido registrado</AlertTitle>
          <AlertDescription>
            {REQUEST_TYPE_LABEL[created.type]} de {formatUnits(created.quantity)} un. de {created.partName} para{' '}
            {created.dealerName}, com status “Aberto”.
          </AlertDescription>
        </Alert>
      )}
      <RiskTable state={risk.state} onRetry={risk.retry} onRequest={setTarget} />
      <RequestsCard state={requests.state} onRetry={requests.retry} />
      <RequestDialog
        row={target}
        horizon={filters.horizon}
        onClose={() => setTarget(null)}
        onCreated={onCreated}
        onDuplicate={refreshAfterWrite}
      />
    </section>
  );
}
