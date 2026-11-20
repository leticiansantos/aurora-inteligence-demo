import { EmptyState } from '@/components/StateViews';

export function SectionPage({ title, description }: { title: string; description: string }) {
  return (
    <section aria-labelledby="section-title" className="mx-auto max-w-6xl">
      <h2 id="section-title" className="font-display text-3xl font-semibold text-foreground">
        {title}
      </h2>
      <p className="mt-1 mb-8 max-w-[65ch] text-muted-foreground">{description}</p>
      <EmptyState title="Em construção" description="Esta tela receberá dados nas próximas etapas da jornada." />
    </section>
  );
}
