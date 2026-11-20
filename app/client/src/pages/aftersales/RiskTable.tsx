import {
  Badge,
  Button,
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
import { AlertTriangle } from 'lucide-react';
import type { AftersalesRiskResponse, AftersalesRiskRow } from '@/api/aftersales';
import type { Remote } from '@/api/useMarketData';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { formatBrl, formatDays, formatPercent, formatUnits } from '@/lib/format';
import { ACTION_LABEL, effectiveAction, isAttention, REQUEST_TYPE_LABEL, RISK_LABEL, STATUS_LABEL } from './labels';

function RiskBadge({ level }: { level: AftersalesRiskRow['riskLevel'] }) {
  const attn = isAttention(level);
  return (
    <Badge
      variant="outline"
      className={`gap-1 ${attn ? 'border-accent text-foreground' : 'text-muted-foreground'} ${level === 'critical' ? 'bg-accent/15 font-semibold' : ''}`}
    >
      {attn && <AlertTriangle className="h-3 w-3 text-accent" aria-hidden />}
      {RISK_LABEL[level]}
    </Badge>
  );
}

function ActionCell({ row, onRequest }: { row: AftersalesRiskRow; onRequest: (r: AftersalesRiskRow) => void }) {
  if (row.openRequest)
    return (
      <span className="text-sm">
        {REQUEST_TYPE_LABEL[row.openRequest.type]}:{' '}
        <Badge variant="secondary">{STATUS_LABEL[row.openRequest.status]}</Badge>
      </span>
    );
  if (row.action === 'monitor') return <span className="text-sm text-muted-foreground">Sem ação necessária</span>;
  return (
    <Button size="sm" variant="outline" onClick={() => onRequest(row)}>
      {effectiveAction(row) === 'transfer' ? 'Solicitar transferência' : 'Solicitar reposição'}
      <span className="sr-only">
        {' '}
        de {row.partName} para {row.dealerName}
      </span>
    </Button>
  );
}

export function RiskTable({
  state,
  onRetry,
  onRequest,
}: {
  state: Remote<AftersalesRiskResponse>;
  onRetry: () => void;
  onRequest: (r: AftersalesRiskRow) => void;
}) {
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle className="font-display text-xl">Ranking de risco de ruptura</CardTitle>
        <CardDescription>
          {state.phase === 'ready'
            ? `${formatUnits(state.data.rows.length)} de ${formatUnits(state.data.total)} combinações de peça e concessionária, ordenadas pela venda perdida estimada.`
            : 'Combinações de peça e concessionária, ordenadas pela venda perdida estimada. O risco considera o estoque em mão mais o que está em pedido.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {state.phase === 'loading' && (
          <div role="status" aria-live="polite" className="space-y-2">
            <span className="sr-only">Carregando ranking de risco…</span>
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        )}
        {state.phase === 'error' && (
          <ErrorState title="Não foi possível carregar o ranking de risco" message={state.message} onRetry={onRetry} />
        )}
        {state.phase === 'ready' && state.data.rows.length === 0 && (
          <EmptyState title="Nenhuma peça nesta seleção" description="Ajuste os filtros para ver outras combinações." />
        )}
        {state.phase === 'ready' && state.data.rows.length > 0 && (
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Peça</TableHead>
                  <TableHead>Concessionária</TableHead>
                  <TableHead className="text-right">Estoque em mão</TableHead>
                  <TableHead className="text-right">Dias de estoque</TableHead>
                  <TableHead className="text-right">Prob. de ruptura</TableHead>
                  <TableHead>Risco</TableHead>
                  <TableHead className="text-right">Venda perdida est.</TableHead>
                  <TableHead>Ação recomendada e pedido</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {state.data.rows.map((r) => (
                  <TableRow key={r.key}>
                    <TableCell>
                      <div className="font-medium">{r.partName}</div>
                      <div className="text-xs text-muted-foreground">{r.categoryName}</div>
                    </TableCell>
                    <TableCell>{r.dealerName}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatUnits(r.stockUnits)}
                      {r.onOrderUnits > 0 && (
                        <div className="text-xs text-muted-foreground">+{formatUnits(r.onOrderUnits)} em pedido</div>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.daysOfStock === null ? '—' : formatDays(r.daysOfStock)}
                      <div className="text-xs text-muted-foreground">prazo {r.leadTimeDays} dias</div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatPercent(r.stockoutProbability, 0)}</TableCell>
                    <TableCell>
                      <RiskBadge level={r.riskLevel} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatBrl(r.lostSalesBrl)}</TableCell>
                    <TableCell className="text-sm">
                      {ACTION_LABEL[effectiveAction(r)]}
                      {r.action !== 'monitor' && (
                        <div className="text-xs text-muted-foreground">
                          {formatUnits(r.recommendedQty)} un.
                          {r.transferFrom ? ` de ${r.transferFrom.dealerName}` : ''}
                        </div>
                      )}
                      <div className="mt-1.5">
                        <ActionCell row={r} onRequest={onRequest} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
