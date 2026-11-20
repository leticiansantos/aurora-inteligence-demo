# Brand: Aurora Motors

The demo uses a fictional automaker, **Aurora Motors**, with the assistant **Lumi**. Nothing here belongs to a real company.

## Where things live

| File | Purpose |
| --- | --- |
| `src/brand/brand.config.ts` | Name, assistant name, tagline, page title, light and dark palettes, chart colours |
| `src/brand/applyBrand.ts` | Injects the palette as CSS variables at startup and sets `document.title` |
| `src/brand/AuroraLogo.tsx` | Original logo mark (inline SVG) and wordmark |
| `public/favicon.svg`, `public/site.webmanifest` | Favicon and install name |

## Re-skinning for another customer

1. Edit `brand.config.ts` (names, tagline, both palettes).
2. Replace the SVG in `AuroraLogo.tsx` and `public/favicon.svg`.
3. Keep UI copy in pt-BR; read names from `brand` instead of hard-coding them.

## Rules

- Use only palette tokens (`bg-primary`, `text-muted-foreground`, `var(--chart-1)`…). No hard-coded hex values in components.
- The app is **light-only**: `index.html` sets `class="light"` and `applyBrand` injects only the light palette. The `dark` palette in `brand.config.ts` is kept for a future theme but is not applied.
- Do not add third-party brand names, logos or marks.

## Visual identity

- **Palette (instrument cluster):** graphite neutrals, steel blue `#1f4e79` as the brand colour, and amber
  `#b5651d` / `#e39a45` (dark) reserved for attention: risk, alerts and the active navigation item.
- **Masthead:** fixed graphite band (`--masthead`); active section marked by an amber underline.
- **Type:** Barlow for UI text, Barlow Semi Condensed (`font-display`) for page titles. Both are self-hosted via
  `@fontsource`, with tabular figures on by default for numbers.
