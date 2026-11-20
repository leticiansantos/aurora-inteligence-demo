import { useCallback, useEffect, useState } from 'react';

export type Remote<T> =
  | { phase: 'loading' }
  | { phase: 'error'; message: string; status?: number }
  | { phase: 'ready'; data: T };

type Settled<T> = { key: string; attempt: number; result: Exclude<Remote<T>, { phase: 'loading' }> };

/**
 * Fetches `load` whenever `key` changes or `retry` is called. While a request for the current key is in flight the
 * state is `loading` (never the previous selection's numbers); `lastData` keeps the last good payload for chrome
 * that must stay usable meanwhile (e.g. the month picker bounds).
 */
export function useRemote<T>(
  load: (signal: AbortSignal) => Promise<T>,
  key: string
): { state: Remote<T>; lastData: T | null; retry: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [lastData, setLastData] = useState<T | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal)
      .then((data) => {
        setSettled({ key, attempt, result: { phase: 'ready', data } });
        setLastData(data);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const status =
          typeof err === 'object' && err && 'status' in err ? Number((err as { status: unknown }).status) : undefined;
        setSettled({
          key,
          attempt,
          result: {
            phase: 'error',
            message:
              err instanceof Error ? err.message : 'Não foi possível carregar os dados de mercado. Tente novamente.',
            status,
          },
        });
      });
    return () => controller.abort();
    // `load` is recreated on every render; `key` identifies the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  const state: Remote<T> =
    settled && settled.key === key && settled.attempt === attempt ? settled.result : { phase: 'loading' };
  return { state, lastData, retry };
}
