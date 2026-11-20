import { useMemo } from 'react';

/** Resolve a brand CSS variable to a concrete colour (ECharts draws on canvas and cannot read var()). */
export function useCssColor(name: string, fallback: string): string {
  return useMemo(() => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
    return v || fallback;
  }, [name, fallback]);
}
