import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
} from '@databricks/appkit-ui/react';
import type { AftersalesRequestListResponse } from '@/api/aftersales';
import type { Remote } from '@/api/useMarketData';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { formatUnits } from '@/lib/format';
import { REQUEST_TYPE_LABEL, STATUS_LABEL } from './labels';

const DT = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' });

export function RequestsCard({
  state,
  onRetry,
}: {
  state: Remote<AftersalesRequestListResponse>;
  onRetry: () => void;
}) {
  return (
    <Card className="shadow-none">
      <CardHeader>
        <CardTitle className="font-display text-xl">Pedidos recentes</CardTitle>
        <CardDescription>
          Pedidos de reposição e transferência registrados nesta demonstração, do mais novo ao mais antigo.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {state.phase === 'loading' && (
          <div role="status" aria-live="polite" className="space-y-2">
            <span className="sr-only">Carregando pedidos…</span>
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
          </div>
        )}
        {state.phase === 'error' && (
          <ErrorState title="Não foi possível carregar os pedidos" message={state.message} onRetry={onRetry} />
        )}
        {state.phase === 'ready' && state.data.requests.length === 0 && (
          <EmptyState
            title="Nenhum pedido ainda"
            description="Use as ações do ranking de risco para solicitar uma reposição ou transferência."
          />
        )}
        {state.phase === 'ready' && state.data.requests.length > 0 && (
          <ul className="m-0 list-none divide-y p-0">
            {state.data.requests.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>
                  <span className="font-medium">{REQUEST_TYPE_LABEL[r.type]}</span> de {formatUnits(r.quantity)} un. de{' '}
                  {r.partName} para {r.dealerName}
                </span>
                <span className="flex items-center gap-3">
                  <time dateTime={r.createdAt} className="text-xs text-muted-foreground">
                    {DT.format(new Date(r.createdAt))}
                  </time>
                  <Badge variant="secondary">{STATUS_LABEL[r.status]}</Badge>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
