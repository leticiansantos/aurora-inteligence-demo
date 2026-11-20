/**
 * Single source of truth for the demo's identity.
 * Aurora Motors is a fictional automaker created for this demo.
 * To re-skin the app for another customer, edit this file and AuroraLogo.tsx.
 */
export interface BrandPalette {
  background: string;
  foreground: string;
  card: string;
  primary: string;
  primaryForeground: string;
  secondary: string;
  muted: string;
  mutedForeground: string;
  accent: string;
  accentForeground: string;
  border: string;
  ring: string;
  /** Categorical series colours for charts, in order of use. */
  chart: [string, string, string, string, string];
}

export interface BrandConfig {
  name: string;
  /** Short name used in tight spaces. */
  shortName: string;
  assistantName: string;
  tagline: string;
  appTitle: string;
  light: BrandPalette;
  dark: BrandPalette;
}

export const brand: BrandConfig = {
  name: 'Aurora Motors',
  shortName: 'Aurora',
  assistantName: 'Lumi',
  tagline: 'Inteligência de dados para o pós-venda automotivo',
  appTitle: 'Aurora Motors · Auto Intelligence',
  /* Instrument-cluster palette: graphite neutrals, steel-blue brand colour,
   amber reserved for attention (risk, alerts), like a dashboard telltale. */
  light: {
    background: '#f3f5f7',
    foreground: '#1b2128',
    card: '#ffffff',
    primary: '#1f4e79',
    primaryForeground: '#ffffff',
    secondary: '#e8ecf0',
    muted: '#e8ecf0',
    mutedForeground: '#56626e',
    accent: '#b5651d',
    accentForeground: '#ffffff',
    border: '#d8dee4',
    ring: '#1f4e79',
    chart: ['#1f4e79', '#5b8db8', '#b5651d', '#6b7b8c', '#a8c4dc'],
  },
  dark: {
    background: '#12161a',
    foreground: '#e6eaee',
    card: '#1a2026',
    primary: '#7aa9d6',
    primaryForeground: '#0f1418',
    secondary: '#232b33',
    muted: '#232b33',
    mutedForeground: '#9aa6b2',
    accent: '#e39a45',
    accentForeground: '#15100a',
    border: '#2c353e',
    ring: '#7aa9d6',
    chart: ['#7aa9d6', '#b3cde6', '#e39a45', '#8d9ba8', '#4f7fab'],
  },
};
