import { useMemo } from 'react';
import {
  Badge,
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
import type { AftersalesForecastResponse } from '@/api/aftersales';
import type { Remote } from '@/api/useMarketData';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { formatPercent, formatUnits } from '@/lib/format';
import { useCssColor } from '../market/useChartColor';

const ACTUAL = 'Venda real';
const FORECAST = 'Previsão';
const UPPER = 'Limite superior (80%)';
const LOWER = 'Limite inferior (80%)';

const weekLabel = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
const weekLong = (iso: string) => iso.split('-').reverse().join('/');

export function ForecastCard({ state, onRetry }: { state: Remote<AftersalesForecastResponse>; onRetry: () => void }) {
  const actual = useCssColor('foreground', '#1b2128');
  const forecast = useCssColor('chart-2', '#5b8db8');
  const band = useCssColor('border', '#d8dee4');
  const axisText = useCssColor('muted-foreground', '#56626e');

  const rows = useMemo(
    () =>
      state.phase === 'ready'
        ? state.data.series.map((p) => ({
            semana: weekLabel(p.weekStart),
            [ACTUAL]: p.actualUnits,
            [FORECAST]: p.forecastUnits,
            [UPPER]: p.upperUnits,
            [LOWER]: p.lowerUnits,
          }))
        : [],
    [state]
  );
  const line = (name: string, color: string, extra: object = {}) => ({
    type: 'line',
    name,
    data: rows.map((r) => (r as Record<string, unknown>)[name]),
    showSymbol: false,
    smooth: false,
    color,
    connectNulls: false,
    tooltip: { valueFormatter: (v: number) => formatUnits(v) },
    ...extra,
  });

  const acc = state.phase === 'ready' ? state.data.accuracy : null;
  const first = state.phase === 'ready' ? state.data.series.find((p) => p.isFuture) : undefined;

  return (
    <Card className="shadow-none">
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <CardTitle className="font-display text-xl">Previsão de demanda × venda real</CardTitle>
          {acc && (
            <Badge
              variant="outline"
              className={acc.wape < acc.baselineWape ? 'text-foreground' : 'border-accent text-foreground'}
            >
              {acc.wape < acc.baselineWape
                ? `Erro ${formatPercent(1 - acc.wape / acc.baselineWape, 0)} menor que a linha de base`
                : 'Modelo não supera a linha de base'}
            </Badge>
          )}
        </div>
        <CardDescription>
          Unidades por semana somadas na seleção.
          {first ? ` As semanas a partir de ${weekLong(first.weekStart)} são previsão.` : ''}
          {acc
            ? ` No período de teste (13 semanas) o erro do modelo (WAPE) foi ${formatPercent(acc.wape, 1)}, contra ${formatPercent(acc.baselineWape, 1)} da linha de base sazonal.`
            : ''}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {state.phase === 'loading' && (
          <div role="status" aria-live="polite">
            <span className="sr-only">Carregando previsão…</span>
            <Skeleton className="bg-muted h-[280px] w-full" />
          </div>
        )}
        {state.phase === 'error' && (
          <ErrorState title="Não foi possível carregar a previsão" message={state.message} onRetry={onRetry} />
        )}
        {state.phase === 'ready' && state.data.series.length === 0 && (
          <EmptyState title="Sem previsão para a seleção" description="Escolha outra concessionária ou categoria." />
        )}
        {state.phase === 'ready' && rows.length > 0 && (
          <>
            <LineChart
              data={rows}
              xKey="semana"
              yKey={[ACTUAL, FORECAST]}
              height={280}
              showLegend
              colors={[actual, forecast]}
              smooth={false}
              ariaLabel="Venda real e previsão de demanda semanal, em unidades, com intervalo de 80%"
              valueFormatter={(v) => formatUnits(Number(v))}
              options={{
                grid: { left: 56, right: 16, top: 40, bottom: 28 },
                legend: { top: 0, left: 'center', data: [ACTUAL, FORECAST], textStyle: { color: axisText } },
                xAxis: {
                  type: 'category',
                  data: rows.map((r) => r.semana),
                  name: '',
                  boundaryGap: false,
                  axisLabel: { color: axisText, interval: Math.max(0, Math.ceil(rows.length / 10) - 1) },
                  axisTick: { show: false },
                },
                yAxis: { type: 'value', name: '', axisLabel: { color: axisText, formatter: formatUnits } },
                series: [
                  line(UPPER, band, { lineStyle: { type: 'dotted', width: 1.5 } }),
                  line(LOWER, band, { lineStyle: { type: 'dotted', width: 1.5 } }),
                  line(FORECAST, forecast, { lineStyle: { type: 'dashed', width: 2.5 } }),
                  line(ACTUAL, actual, { lineStyle: { width: 2.5 } }),
                ],
              }}
            />
            <details className="text-sm">
              <summary className="cursor-pointer text-primary underline underline-offset-2">Ver como tabela</summary>
              <div className="mt-2 max-h-64 overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Semana de</TableHead>
                      <TableHead className="text-right">Venda real</TableHead>
                      <TableHead className="text-right">Previsão</TableHead>
                      <TableHead className="text-right">Intervalo de 80%</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[...state.data.series].reverse().map((p) => (
                      <TableRow key={p.weekStart}>
                        <TableCell>
                          {weekLong(p.weekStart)}
                          {p.isFuture ? ' (futuro)' : ''}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {p.actualUnits === null ? '—' : formatUnits(p.actualUnits)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {p.forecastUnits === null ? '—' : formatUnits(p.forecastUnits)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {p.lowerUnits === null || p.upperUnits === null
                            ? '—'
                            : `${formatUnits(p.lowerUnits)} a ${formatUnits(p.upperUnits)}`}
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
