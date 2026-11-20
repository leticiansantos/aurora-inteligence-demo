import { Badge, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@databricks/appkit-ui/react';
import { useHealth } from '@/api/useHealth';
import type { HealthStatus } from '@/api/health';

const LABELS: Record<HealthStatus, string> = {
  ok: 'Operacional',
  degraded: 'Degradado',
  down: 'Indisponível',
};

const DOT: Record<HealthStatus | 'loading' | 'error', string> = {
  ok: 'bg-emerald-400',
  degraded: 'bg-amber-400',
  down: 'bg-red-400',
  loading: 'bg-white/50 animate-pulse',
  error: 'bg-red-400',
};

export function HealthBadge() {
  const { state, refresh } = useHealth();

  let key: HealthStatus | 'loading' | 'error';
  let label: string;
  let detail: string;
  if (state.phase === 'loading') {
    key = 'loading';
    label = 'Verificando…';
    detail = 'Consultando /api/health';
  } else if (state.phase === 'error') {
    key = 'error';
    label = 'Sem resposta';
    detail = state.message;
  } else {
    const { data } = state;
    key = data.status;
    label = LABELS[data.status];
    const uc = data.unityCatalog;
    detail = uc.reachable
      ? `v${data.version} · ${uc.catalog}.${uc.schema} ${uc.schemaExists ? 'encontrado' : 'não encontrado'}${uc.latencyMs != null ? ` · ${uc.latencyMs} ms` : ''}`
      : `v${data.version} · Unity Catalog inacessível${uc.error ? `: ${uc.error}` : ''}`;
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button type="button" onClick={refresh} className="rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white" aria-label={`Estado do serviço: ${label}. ${detail}. Clique para atualizar.`}>
            <Badge variant="outline" className="gap-2 border-white/20 bg-transparent font-normal text-[color:var(--masthead-foreground)]">
              <span aria-hidden className={`h-2 w-2 rounded-full ${DOT[key]}`} />
              {label}
            </Badge>
          </button>
        </TooltipTrigger>
        <TooltipContent>{detail}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
