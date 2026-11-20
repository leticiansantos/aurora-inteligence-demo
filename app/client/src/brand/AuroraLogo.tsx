import { brand } from './brand.config';

/** Original Aurora Motors mark: an open "A" crossed by a horizon line. Flat, single colour. */
export function AuroraMark({ className = 'h-7 w-7' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden focusable="false">
      <path d="M5 27 L16 5 L27 27" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="square" strokeLinejoin="miter" />
      <path d="M2 19 H30" stroke="var(--accent)" strokeWidth="2.4" />
    </svg>
  );
}

export function AuroraLogo() {
  return (
    <span className="inline-flex items-center gap-2.5 text-white">
      <AuroraMark />
      <span className="font-display text-xl font-semibold leading-none">{brand.name}</span>
    </span>
  );
}
