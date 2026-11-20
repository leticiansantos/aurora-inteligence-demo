import { brand, type BrandPalette } from './brand.config';

function block(p: BrandPalette): string {
  const v: Record<string, string> = {
    background: p.background,
    foreground: p.foreground,
    card: p.card,
    'card-foreground': p.foreground,
    popover: p.card,
    'popover-foreground': p.foreground,
    primary: p.primary,
    'primary-foreground': p.primaryForeground,
    secondary: p.secondary,
    'secondary-foreground': p.foreground,
    muted: p.muted,
    'muted-foreground': p.mutedForeground,
    accent: p.accent,
    'accent-foreground': p.accentForeground,
    border: p.border,
    input: p.border,
    ring: p.ring,
    'sidebar-primary': p.primary,
    'sidebar-ring': p.ring,
  };
  p.chart.forEach((c, i) => (v[`chart-${i + 1}`] = c));
  return Object.entries(v)
    .map(([k, val]) => `--${k}:${val};`)
    .join('');
}

/** The app is light-only: <html class="light"> disables AppKit's `:root:not(.light)` dark tokens.
 * Injects the light brand palette as CSS variables and sets the document title. */
export function applyBrand(): void {
  const style = document.createElement('style');
  style.dataset.brand = brand.shortName;
  document.documentElement.classList.add('light');
  document.documentElement.classList.remove('dark');
  style.textContent = `:root{${block(brand.light)}}`;
  document.head.appendChild(style);
  document.title = brand.appTitle;
}
