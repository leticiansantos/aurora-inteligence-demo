import { Button, GenieChatInput, GenieChatMessageList, useGenieChat } from '@databricks/appkit-ui/react';
import { RotateCcw } from 'lucide-react';

/** Alias registered by the server's genie plugin (server.ts). */
const ALIAS = 'market';

/** Same questions as the Genie Agent's sample questions (scripts/genie/build_space.py). */
const SUGGESTIONS = [
  'Qual foi o share da Aurora Motors em automóveis nos últimos 12 meses?',
  'Quais as 10 marcas que mais emplacaram em setembro de 2026?',
  'Como evoluiu o mercado de comerciais leves de 2019 a 2026?',
  'Quais os modelos mais vendidos da Aurora Motors em 2025?',
  'Quais marcas de automóveis mais cresceram de janeiro a setembro de 2026 em relação a 2025?',
];

export function GeniePage({ title, description }: { title: string; description: string }) {
  const { messages, status, error, sendMessage, reset, hasPreviousPage, fetchPreviousPage } = useGenieChat({
    alias: ALIAS,
  });
  const busy = status === 'streaming' || status === 'loading-history';
  const empty = messages.length === 0 && status !== 'loading-history';

  return (
    <section aria-labelledby="section-title" className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 id="section-title" className="font-display text-3xl font-semibold text-foreground">
            {title}
          </h2>
          <p className="mt-1 max-w-[65ch] text-muted-foreground">{description}</p>
        </div>
        {!empty && (
          <Button variant="outline" size="sm" onClick={reset} disabled={busy}>
            <RotateCcw className="mr-2 h-4 w-4" aria-hidden />
            Nova conversa
          </Button>
        )}
      </div>

      <div className="mt-8 flex h-[calc(100vh-16rem)] min-h-[32rem] flex-col rounded-md border bg-card">
        {empty ? (
          <div className="flex flex-1 flex-col justify-center gap-6 px-6 py-10 md:px-10">
            <div className="max-w-[60ch]">
              <h3 className="font-display text-xl font-semibold text-foreground">Pergunte ao mercado</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                O Genie consulta os emplacamentos publicados pela Fenabrave desde 2003, por marca, modelo e segmento,
                e mostra o SQL e os dados de cada resposta. A Aurora Motors é uma marca fictícia, com dados sintéticos
                somados ao mercado real.
              </p>
            </div>
            <ul className="grid gap-2 md:grid-cols-2" aria-label="Perguntas sugeridas">
              {SUGGESTIONS.map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    onClick={() => sendMessage(q)}
                    className="w-full rounded-md border bg-background px-4 py-3 text-left text-sm text-foreground transition-colors hover:border-primary hover:bg-secondary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <GenieChatMessageList
            messages={messages}
            status={status}
            hasPreviousPage={hasPreviousPage}
            onFetchPreviousPage={fetchPreviousPage}
            className="flex-1"
          />
        )}
        {error && (
          <p role="alert" className="border-t px-6 py-3 text-sm text-destructive">
            Não foi possível obter a resposta do Genie. Tente de novo ou reformule a pergunta.
          </p>
        )}
        <div className="border-t p-4">
          <GenieChatInput
            onSend={sendMessage}
            disabled={busy}
            placeholder="Pergunte sobre marcas, modelos, segmentos ou a Aurora Motors…"
          />
        </div>
      </div>
    </section>
  );
}
