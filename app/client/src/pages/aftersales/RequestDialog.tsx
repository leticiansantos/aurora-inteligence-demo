import { useRef, useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Textarea,
} from '@databricks/appkit-ui/react';
import { aftersalesApi, writeErrorCopy } from '@/api/aftersales';
import type { AftersalesErrorCode, AftersalesHorizon, AftersalesRequest, AftersalesRiskRow } from '@/api/aftersales';
import { ErrorState } from '@/components/StateViews';
import { formatUnits } from '@/lib/format';
import { effectiveAction, REQUEST_TYPE_LABEL } from './labels';

const MAX_NOTE = 500;

export function RequestDialog(props: {
  row: AftersalesRiskRow | null;
  horizon: AftersalesHorizon;
  onClose: () => void;
  onCreated: (r: AftersalesRequest) => void;
  /** The server already has an active request for this dealer x part x type: refresh what the page shows. */
  onDuplicate: () => void;
}) {
  // Keyed by row: each opening starts from fresh form state.
  return props.row ? <RequestForm key={props.row.key} {...props} row={props.row} /> : null;
}

function RequestForm({
  row,
  horizon,
  onClose,
  onCreated,
  onDuplicate,
}: {
  row: AftersalesRiskRow;
  horizon: AftersalesHorizon;
  onClose: () => void;
  onCreated: (r: AftersalesRequest) => void;
  onDuplicate: () => void;
}) {
  const [qty, setQty] = useState(String(Math.max(1, row.recommendedQty)));
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // State updates are async: a ref blocks a double click or Enter before `busy` re-renders the button disabled.
  const inFlight = useRef(false);

  const type = effectiveAction(row) === 'transfer' ? 'transfer' : 'reorder';
  const n = Number(qty);
  const qtyOk = /^\d+$/.test(qty) && n >= 1 && n <= 100000;
  const maxTransfer = row.transferFrom?.availableUnits;
  const overTransfer = type === 'transfer' && maxTransfer !== undefined && qtyOk && n > maxTransfer;

  async function submit() {
    if (!qtyOk || overTransfer || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const { request } = await aftersalesApi.createRequest({
        dealerId: row.dealerId,
        partId: row.partId,
        type,
        quantity: n,
        horizonDays: horizon,
        ...(type === 'transfer' && row.transferFrom ? { fromDealerId: row.transferFrom.dealerId } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      });
      onCreated(request);
    } catch (err) {
      const e = err as { status?: number; code?: AftersalesErrorCode };
      setError(writeErrorCopy(e.status ?? 0, e.code));
      setBusy(false);
      inFlight.current = false;
      if (e.code === 'duplicate_request' || e.status === 409) onDuplicate();
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{type === 'transfer' ? 'Solicitar transferência' : 'Solicitar reposição'}</DialogTitle>
          <DialogDescription>
            Confira os dados antes de confirmar. O pedido ficará com status “Aberto”.
          </DialogDescription>
        </DialogHeader>
        <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Peça</dt>
          <dd className="m-0 font-medium">{row.partName}</dd>
          <dt className="text-muted-foreground">Destino</dt>
          <dd className="m-0 font-medium">{row.dealerName}</dd>
          {type === 'transfer' && row.transferFrom && (
            <>
              <dt className="text-muted-foreground">Origem</dt>
              <dd className="m-0 font-medium">
                {row.transferFrom.dealerName} ({formatUnits(row.transferFrom.availableUnits)} un. disponíveis)
              </dd>
            </>
          )}
          <dt className="text-muted-foreground">Tipo</dt>
          <dd className="m-0 font-medium">{REQUEST_TYPE_LABEL[type]}</dd>
          <dt className="text-muted-foreground">Sugerido</dt>
          <dd className="m-0 font-medium">{formatUnits(row.recommendedQty)} un.</dd>
        </dl>
        <div className="space-y-1.5">
          <Label htmlFor="req-qty">Quantidade (unidades)</Label>
          <Input
            id="req-qty"
            inputMode="numeric"
            value={qty}
            aria-invalid={!qtyOk || overTransfer}
            aria-describedby="req-qty-help"
            onChange={(e) => setQty(e.target.value)}
            className="w-40"
          />
          <p
            id="req-qty-help"
            className={`text-xs ${!qtyOk || overTransfer ? 'text-destructive' : 'text-muted-foreground'}`}
          >
            {!qtyOk
              ? 'Informe um número inteiro entre 1 e 100.000.'
              : overTransfer
                ? `A origem tem só ${formatUnits(maxTransfer ?? 0)} unidades disponíveis.`
                : 'Ajuste se necessário.'}
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="req-note">Observação (opcional)</Label>
          <Textarea
            id="req-note"
            value={note}
            maxLength={MAX_NOTE}
            rows={2}
            onChange={(e) => setNote(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            {note.length}/{MAX_NOTE}
          </p>
        </div>
        {error && <ErrorState title="Não foi possível registrar o pedido" message={error} />}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancelar
          </Button>
          <Button onClick={() => void submit()} disabled={busy || !qtyOk || overTransfer}>
            {busy ? 'Enviando…' : 'Confirmar pedido'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
