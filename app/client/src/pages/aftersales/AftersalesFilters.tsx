import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  ToggleGroup,
  ToggleGroupItem,
} from '@databricks/appkit-ui/react';
import { AFTERSALES_HORIZONS } from '@/api/aftersales';
import type { AftersalesFiltersResponse, AftersalesHorizon } from '@/api/aftersales';
import { horizonLabel } from './labels';

export interface AftersalesFilterState {
  dealer: string; // "all" or id
  category: string; // "all" or id
  horizon: AftersalesHorizon;
  onlyHigh: boolean;
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span id={id} className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}

export function AftersalesFilters({
  value,
  onChange,
  options,
}: {
  value: AftersalesFilterState;
  onChange: (v: AftersalesFilterState) => void;
  options: AftersalesFiltersResponse | null;
}) {
  const horizons = options?.horizons ?? AFTERSALES_HORIZONS;
  return (
    <div
      role="group"
      aria-label="Filtros"
      className="flex flex-wrap items-end gap-x-8 gap-y-4 border-y bg-card/60 px-1 py-4"
    >
      <Field id="flt-dealer" label="Concessionária">
        <Select value={value.dealer} disabled={!options} onValueChange={(dealer) => onChange({ ...value, dealer })}>
          <SelectTrigger size="sm" className="w-[17rem]" aria-labelledby="flt-dealer">
            <SelectValue placeholder="Todas" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todas as concessionárias</SelectItem>
            {options?.dealers.map((d) => (
              <SelectItem key={d.id} value={d.id}>
                {d.name} ({d.state})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field id="flt-category" label="Categoria de peça">
        <Select
          value={value.category}
          disabled={!options}
          onValueChange={(category) => onChange({ ...value, category })}
        >
          <SelectTrigger size="sm" className="w-[11rem]" aria-labelledby="flt-category">
            <SelectValue placeholder="Todas" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todas as categorias</SelectItem>
            {options?.categories.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field id="flt-horizon" label="Horizonte da previsão">
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={String(value.horizon)}
          aria-labelledby="flt-horizon"
          onValueChange={(v) => v && onChange({ ...value, horizon: Number(v) as AftersalesHorizon })}
        >
          {horizons.map((h) => (
            <ToggleGroupItem
              key={h}
              value={String(h)}
              className="px-3 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
            >
              {horizonLabel(h)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </Field>
      <Field id="flt-level" label="Risco exibido">
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={value.onlyHigh ? 'high' : 'all'}
          aria-labelledby="flt-level"
          onValueChange={(v) => v && onChange({ ...value, onlyHigh: v === 'high' })}
        >
          <ToggleGroupItem
            value="all"
            className="px-3 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          >
            Todos
          </ToggleGroupItem>
          <ToggleGroupItem
            value="high"
            className="px-3 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          >
            Alto e crítico
          </ToggleGroupItem>
        </ToggleGroup>
      </Field>
    </div>
  );
}
