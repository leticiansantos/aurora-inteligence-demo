import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { marketApi, MARKET_DEFAULTS } from '@/api/market';
import type { MarketPeriod, MarketQuery, MarketSegment, MarketView } from '@/api/market';
import { useRemote } from '@/api/useMarketData';
import { BrandRankingCard } from './market/BrandRankingCard';
import { KpiRow } from './market/KpiRow';
import { MarketFilters, type MarketFilterState } from './market/MarketFilters';
import { auroraAbsenceReason } from './market/labels';
import { TimeSeriesCard } from './market/TimeSeriesCard';
import { TopModelsCard } from './market/TopModelsCard';

const pick = <T extends string>(v: string | null, allowed: readonly T[], fallback: T): T =>
  allowed.includes(v as T) ? (v as T) : fallback;

/** Filters live in the URL (?segmento=&periodo=&visao=&mes=) so a view can be shared and survives a reload. */
function useFilters(): [MarketFilterState, (f: MarketFilterState) => void] {
  const [params, setParams] = useSearchParams();
  const filters = useMemo<MarketFilterState>(() => {
    const month = params.get('mes');
    return {
      segment: pick<MarketSegment>(
        params.get('segmento'),
        ['total', 'automoveis', 'comerciais_leves'],
        MARKET_DEFAULTS.segment
      ),
      period: pick<MarketPeriod>(params.get('periodo'), ['12m', '24m', '60m', 'all'], MARKET_DEFAULTS.period),
      view: pick<MarketView>(params.get('visao'), ['with_aurora', 'real'], MARKET_DEFAULTS.view),
      month: month && /^\d{4}-(0[1-9]|1[0-2])$/.test(month) ? month : null,
    };
  }, [params]);
  const set = useCallback(
    (f: MarketFilterState) => {
      const next = new URLSearchParams();
      if (f.segment !== MARKET_DEFAULTS.segment) next.set('segmento', f.segment);
      if (f.period !== MARKET_DEFAULTS.period) next.set('periodo', f.period);
      if (f.view !== MARKET_DEFAULTS.view) next.set('visao', f.view);
      if (f.month) next.set('mes', f.month);
      const mock = params.get('mock');
      if (mock) next.set('mock', mock);
      setParams(next, { replace: true });
    },
    [params, setParams]
  );
  return [filters, set];
}

export function MarketPage({ title, description }: { title: string; description: string }) {
  const [filters, setFilters] = useFilters();
  const { segment, period, view, month } = filters;
  const q: MarketQuery = useMemo(
    () => ({ segment, period, view, ...(month ? { month } : {}) }),
    [segment, period, view, month]
  );
  const key = `${segment}|${period}|${view}|${month ?? ''}`;

  const summary = useRemote((s) => marketApi.summary(q, s), key);
  // The time series always ends at the latest month: it does not depend on the reference month.
  const series = useRemote((s) => marketApi.timeseries({ segment, period, view }, s), `${segment}|${period}|${view}`);
  const brands = useRemote((s) => marketApi.brands({ ...q, limit: 25 }, s), key);
  const models = useRemote((s) => marketApi.models({ ...q, limit: 10 }, s), key);

  // Last known coverage keeps the month picker usable while data reloads.
  const coverage = summary.lastData?.coverage ?? null;

  const absence = auroraAbsenceReason(segment, view);

  return (
    <section aria-labelledby="section-title" className="mx-auto max-w-6xl space-y-8">
      <header>
        <h2 id="section-title" className="font-display text-3xl font-semibold text-foreground">
          {title}
        </h2>
        <p className="mt-1 max-w-[65ch] text-muted-foreground">{description}</p>
      </header>
      <MarketFilters query={filters} onChange={setFilters} coverage={coverage} />
      <KpiRow state={summary.state} onRetry={summary.retry} absence={absence} />
      <TimeSeriesCard state={series.state} onRetry={series.retry} segment={segment} period={period} refMonth={month} />
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <BrandRankingCard state={brands.state} onRetry={brands.retry} />
        </div>
        <div>
          <TopModelsCard state={models.state} onRetry={models.retry} />
        </div>
      </div>
    </section>
  );
}
