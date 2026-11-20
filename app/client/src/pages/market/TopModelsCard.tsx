import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@databricks/appkit-ui/react';
import type { MarketModelsResponse } from '@/api/market';
import type { Remote } from '@/api/useMarketData';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { formatMonthLong, formatMonthShort, formatPercent, formatUnits } from '@/lib/format';

export function TopModelsCard({ state, onRetry }: { state: Remote<MarketModelsResponse>; onRetry: () => void }) {
  const d = state.phase === 'ready' ? state.data : null;
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle className="font-display text-xl">Modelos mais emplacados</CardTitle>
        <CardDescription>
          {d?.available
            ? `Top ${d.rows.length} de ${formatMonthLong(d.month)}. Os modelos publicados cobrem ${formatPercent(d.coveredUnits / d.totalUnits, 0)} do mercado.`
            : 'Ranking de modelos do mês de referência.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {state.phase === 'loading' && (
          <div role="status" aria-live="polite" className="space-y-2">
            <span className="sr-only">Carregando modelos…</span>
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        )}
        {state.phase === 'error' && (
          <ErrorState title="Não foi possível carregar os modelos" message={state.message} onRetry={onRetry} />
        )}
        {d && !d.available && (
          <EmptyState
            title="Sem ranking de modelos"
            description="Não há tabela de modelos publicada para esta seleção."
          />
        )}
        {d && d.available && (
          <>
            {d.month !== d.latestMonth && (
              <p
                className="mb-3 rounded-sm border-l-2 border-accent bg-accent/10 px-3 py-2 text-sm text-foreground"
                role="note"
              >
                Modelos de {formatMonthShort(d.month)}: a edição de {formatMonthShort(d.latestMonth)} não publicou
                ranking de modelos.
              </p>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10 text-right">#</TableHead>
                  <TableHead>Modelo</TableHead>
                  <TableHead>Marca</TableHead>
                  <TableHead className="text-right">Unidades</TableHead>
                  <TableHead className="text-right">Participação</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.rows.map((r) => (
                  <TableRow key={`${r.brand}-${r.model}`} className={r.isAurora ? 'bg-accent/10 font-semibold' : ''}>
                    <TableCell className="text-right tabular-nums text-muted-foreground">{r.rank}</TableCell>
                    <TableCell>{r.model}</TableCell>
                    <TableCell>
                      <span className="inline-flex items-center gap-2">
                        {r.isAurora ? 'Aurora Motors' : r.brand}
                        {r.isAurora && (
                          <Badge variant="outline" className="border-accent px-1.5 py-0 text-[10px] text-foreground">
                            sintética
                          </Badge>
                        )}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatUnits(r.units)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPercent(r.share, 1)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </CardContent>
    </Card>
  );
}
