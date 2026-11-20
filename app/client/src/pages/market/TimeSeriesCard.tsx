import { useMemo } from 'react';
import {
  AreaChart,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  LineChart,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@databricks/appkit-ui/react';
import type { MarketPeriod, MarketSegment, MarketTimeseriesResponse } from '@/api/market';
import type { Remote } from '@/api/useMarketData';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { formatCompact, formatMonthLong, formatMonthShort, formatPercent, formatUnits } from '@/lib/format';
import { periodLong, segmentLabel } from './labels';
import { useCssColor } from './useChartColor';

const UNITS = 'Emplacamentos';
const SHARE = 'Participação da Aurora';

export function TimeSeriesCard({
  state,
  onRetry,
  segment,
  period,
  refMonth,
}: {
  state: Remote<MarketTimeseriesResponse>;
  onRetry: () => void;
  segment: MarketSegment;
  period: MarketPeriod;
  /** Selected reference month (YYYY-MM-01) when it is not the latest; marked on the charts. */
  refMonth: string | null;
}) {
  const primary = useCssColor('chart-2', '#5b8db8');
  const amber = useCssColor('accent', '#b5651d');
  const axisText = useCssColor('muted-foreground', '#56626e');
  const gridLine = useCssColor('border', '#d8dee4');
  const axisStrong = useCssColor('foreground', '#1b2128');

  // The chart merges `options` shallowly, so each axis override restates its type and data.
  const xAxis = (labels: string[]) => ({
    type: 'category',
    data: labels,
    name: '',
    boundaryGap: false,
    axisLabel: {
      color: axisText,
      rotate: 0,
      interval: Math.max(0, Math.ceil(labels.length / 8) - 1),
      formatter: (v: string) => v,
    },
    axisLine: { lineStyle: { color: gridLine } },
    axisTick: { show: false },
  });
  // Full series definition (options merge shallowly, so a series override must restate everything it needs).
  const refLabel = refMonth ? formatMonthShort(refMonth) : null;
  // markLine is not registered in the AppKit chart bundle, so the reference month is a highlighted point series.
  const refSeries = (labels: string[], values: (number | null)[], format: (v: number) => string) =>
    refLabel && labels.includes(refLabel)
      ? [
          {
            type: 'line',
            name: 'Mês de referência',
            data: values.map((v, i) => (labels[i] === refLabel ? v : null)),
            symbol: 'circle',
            symbolSize: 11,
            showSymbol: true,
            lineStyle: { opacity: 0 },
            itemStyle: { color: axisStrong, borderColor: '#ffffff', borderWidth: 2 },
            z: 10,
            tooltip: { valueFormatter: (v: number) => format(v) },
          },
        ]
      : [];
  const yAxis = (format: (v: number) => string, max?: number) => ({
    type: 'value',
    name: '',
    max,
    axisLabel: { color: axisText, formatter: format },
    splitLine: { lineStyle: { color: gridLine } },
  });

  const data = useMemo(() => {
    if (state.phase !== 'ready') return null;
    const pts = state.data.points;
    // Aurora only exists from its first month: drop the leading nulls (the chart would draw them as 0%).
    const firstAurora = pts.findIndex((p) => p.auroraShare !== null);
    return {
      units: pts.map((p) => ({ mes: formatMonthShort(p.month), [UNITS]: p.totalUnits })),
      share:
        firstAurora < 0
          ? []
          : pts.slice(firstAurora).map((p) => ({ mes: formatMonthShort(p.month), [SHARE]: p.auroraShare })),
      auroraFrom: firstAurora <= 0 ? null : pts[firstAurora].month,
      hasAurora: firstAurora >= 0,
    };
  }, [state]);

  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle className="font-display text-xl">
          Emplacamentos mensais: {segmentLabel(segment).toLowerCase()}, {periodLong(period)}
        </CardTitle>
        <CardDescription>
          Unidades por mês{data?.hasAurora ? ' e participação da Aurora Motors no mercado' : ''}
          {state.phase === 'ready' && state.data.points.length > 0
            ? `. Série até ${formatMonthLong(state.data.to)}, o mês mais recente; não muda com o mês de referência.${refMonth ? ' O ponto escuro marca o mês de referência.' : ''}`
            : '.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {state.phase === 'loading' && (
          <div role="status" aria-live="polite" className="space-y-3">
            <span className="sr-only">Carregando série mensal…</span>
            <Skeleton className="bg-muted h-[240px] w-full" />
            <Skeleton className="bg-muted h-[130px] w-full" />
          </div>
        )}
        {state.phase === 'error' && (
          <ErrorState title="Não foi possível carregar a série mensal" message={state.message} onRetry={onRetry} />
        )}
        {state.phase === 'ready' && state.data.points.length === 0 && (
          <EmptyState title="Sem dados no período" description="Escolha outro período ou segmento." />
        )}
        {state.phase === 'ready' && data && state.data.points.length > 0 && (
          <>
            <AreaChart
              data={data.units}
              xKey="mes"
              yKey={UNITS}
              height={240}
              showLegend={false}
              colors={[primary]}
              smooth={false}
              ariaLabel={`Emplacamentos mensais, de ${formatMonthShort(state.data.from)} a ${formatMonthShort(state.data.to)}`}
              valueFormatter={(v) => formatUnits(Number(v))}
              options={{
                grid: { left: 56, right: 16, top: 12, bottom: 28 },
                xAxis: xAxis(data.units.map((d) => d.mes)),
                yAxis: yAxis(formatCompact),
                series: [
                  {
                    type: 'line',
                    name: UNITS,
                    data: data.units.map((d) => d[UNITS]),
                    showSymbol: false,
                    smooth: false,
                    color: primary,
                    areaStyle: { opacity: 0.12 },
                    tooltip: { valueFormatter: (v: number) => formatUnits(v) },
                  },
                  ...refSeries(
                    data.units.map((d) => d.mes),
                    data.units.map((d) => d[UNITS]),
                    formatUnits
                  ),
                ],
              }}
            />
            {data.hasAurora ? (
              <div>
                <p className="mb-1 text-sm font-medium text-foreground">
                  Participação da Aurora Motors no mercado
                  {data.auroraFrom ? ` (desde ${formatMonthShort(data.auroraFrom)})` : ''}
                </p>
                <LineChart
                  data={data.share}
                  xKey="mes"
                  yKey={SHARE}
                  height={150}
                  showLegend={false}
                  colors={[amber]}
                  smooth={false}
                  ariaLabel="Participação mensal da Aurora Motors, em percentual do mercado"
                  valueFormatter={(v) => formatPercent(Number(v), 1)}
                  options={{
                    grid: { left: 56, right: 16, top: 8, bottom: 28 },
                    xAxis: xAxis(data.share.map((d) => d.mes)),
                    yAxis: yAxis((v) => formatPercent(v, 1)),
                    series: [
                      {
                        type: 'line',
                        name: SHARE,
                        data: data.share.map((d) => d[SHARE]),
                        showSymbol: false,
                        smooth: false,
                        color: amber,
                        lineStyle: { width: 3 },
                        tooltip: { valueFormatter: (v: number) => formatPercent(v, 1) },
                      },
                      ...refSeries(
                        data.share.map((d) => d.mes),
                        data.share.map((d) => d[SHARE]),
                        (v) => formatPercent(v, 1)
                      ),
                    ],
                  }}
                />
              </div>
            ) : null}
            <details className="text-sm">
              <summary className="cursor-pointer text-primary underline underline-offset-2">Ver como tabela</summary>
              <div className="mt-2 max-h-64 overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Mês</TableHead>
                      <TableHead className="text-right">Emplacamentos</TableHead>
                      <TableHead className="text-right">Participação da Aurora</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[...state.data.points].reverse().map((p) => (
                      <TableRow key={p.month}>
                        <TableCell>{formatMonthLong(p.month)}</TableCell>
                        <TableCell className="text-right tabular-nums">{formatUnits(p.totalUnits)}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {p.auroraShare === null ? '—' : formatPercent(p.auroraShare, 1)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </details>
          </>
        )}
      </CardContent>
    </Card>
  );
}
