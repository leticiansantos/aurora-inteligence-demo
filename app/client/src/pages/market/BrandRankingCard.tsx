import { Fragment, useState } from 'react';
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
  ToggleGroup,
  ToggleGroupItem,
} from '@databricks/appkit-ui/react';
import type { MarketBrandList, MarketBrandRow, MarketBrandsResponse } from '@/api/market';
import type { Remote } from '@/api/useMarketData';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { formatMonthLong, formatMonthShort, formatPercent, formatUnits } from '@/lib/format';

type Scope = 'latest' | 'period';
const VISIBLE_TOP = 10;

function Row({ row, max }: { row: MarketBrandRow; max: number }) {
  const pct = max > 0 ? Math.max(1, (row.share / max) * 100) : 0;
  const bar = row.isAurora ? 'bg-accent' : row.isResidual ? 'bg-muted-foreground/25' : 'bg-primary/70';
  return (
    <li
      className={`grid grid-cols-[1.75rem_minmax(0,12.5rem)_minmax(2rem,1fr)_4.25rem_3.5rem] items-center gap-3 py-1.5 text-sm  ${
        row.isAurora ? 'rounded-sm bg-accent/10 font-semibold' : ''
      } ${row.isResidual ? 'text-muted-foreground italic' : ''}`}
    >
      <span className="text-right tabular-nums text-muted-foreground">{row.rank ?? ''}</span>
      <span className="flex items-center gap-2 truncate" title={row.label}>
        <span className="truncate pr-1">{row.label}</span>
        {row.isAurora && (
          <Badge variant="outline" className="border-accent px-1.5 py-0 text-[10px] text-foreground">
            sintética
          </Badge>
        )}
      </span>
      <span className="h-3 rounded-sm bg-muted/60" aria-hidden>
        <span className={`block h-full rounded-sm ${bar}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="text-right tabular-nums">{formatUnits(row.units)}</span>
      <span className="text-right tabular-nums">{formatPercent(row.share, 1)}</span>
    </li>
  );
}

function List({ list }: { list: MarketBrandList }) {
  if (list.rows.length === 0)
    return (
      <EmptyState title="Sem ranking de marcas" description="Não há ranking de marcas publicado para esta seleção." />
    );
  const ranked = list.rows.filter((r) => !r.isResidual);
  const max = Math.max(0, ...list.rows.map((r) => r.share));
  // Show the top rows, plus Aurora when it ranks lower, so its position is never hidden.
  const aurora = ranked.find((r) => r.isAurora);
  const top = ranked.slice(0, VISIBLE_TOP);
  const extra = aurora && !top.includes(aurora) ? [aurora] : [];
  const shown = [...top, ...extra, ...list.rows.filter((r) => r.isResidual)];
  const gapBefore = extra.length && (aurora?.rank ?? 0) > VISIBLE_TOP + 1 ? top.length : -1;
  const hiddenUnits = ranked.filter((r) => !shown.includes(r)).reduce((a, r) => a + r.units, 0) + list.othersUnits;
  return (
    <>
      {ranked.length === 0 && (
        <p className="mb-2 text-sm text-muted-foreground">
          Este mês só tem o total publicado, sem ranking de marcas (edição prévia).
        </p>
      )}
      <ol className="m-0 list-none p-0" aria-label="Ranking de marcas">
        {shown.map((r, i) => (
          <Fragment key={r.brand}>
            {gapBefore === i && (
              <li aria-hidden className="py-0.5 pl-9 text-xs text-muted-foreground">
                ⋯
              </li>
            )}
            <Row row={r} max={max || r.share} />
          </Fragment>
        ))}
      </ol>
      {hiddenUnits > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          {formatUnits(hiddenUnits)} emplacamentos em outras marcas publicadas, fora das linhas acima.
        </p>
      )}
    </>
  );
}

export function BrandRankingCard({ state, onRetry }: { state: Remote<MarketBrandsResponse>; onRetry: () => void }) {
  const [scope, setScope] = useState<Scope>('latest');
  const list = state.phase === 'ready' ? (scope === 'latest' ? state.data.latestMonth : state.data.period) : null;
  return (
    <Card className="shadow-none">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="font-display text-xl">Ranking de marcas</CardTitle>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={scope}
            aria-label="Escopo do ranking"
            onValueChange={(v) => v && setScope(v as Scope)}
          >
            <ToggleGroupItem
              value="latest"
              className="px-3 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
            >
              Mês de referência
            </ToggleGroupItem>
            <ToggleGroupItem
              value="period"
              className="px-3 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
            >
              Período
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
        <CardDescription>
          {list
            ? scope === 'latest'
              ? `Emplacamentos em ${formatMonthLong(list.to)}. Participação sobre ${formatUnits(list.totalUnits)} unidades.`
              : `Soma de ${formatMonthShort(list.from)} a ${formatMonthShort(list.to)}. O ranking do período é indicativo: marcas fora do top publicado em algum mês ficam em “Outras”.`
            : 'Participação no mercado, com a Aurora Motors destacada.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {state.phase === 'loading' && (
          <div role="status" aria-live="polite" className="space-y-2">
            <span className="sr-only">Carregando ranking…</span>
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-5 w-full" />
            ))}
          </div>
        )}
        {state.phase === 'error' && (
          <ErrorState title="Não foi possível carregar o ranking" message={state.message} onRetry={onRetry} />
        )}
        {list && <List list={list} />}
      </CardContent>
    </Card>
  );
}
