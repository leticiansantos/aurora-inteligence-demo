import { useCallback, useEffect, useState } from 'react';
import { fetchHealth, type HealthResponse } from './health';

export type HealthState =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'ready'; data: HealthResponse };

const REFRESH_MS = 60_000;

export function useHealth(): { state: HealthState; refresh: () => void } {
  const [state, setState] = useState<HealthState>({ phase: 'loading' });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((data) => setState({ phase: 'ready', data }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          phase: 'error',
          message: err instanceof Error ? err.message : 'Falha ao consultar o servidor',
        });
      });
    return () => controller.abort();
  }, [tick]);

  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { state, refresh };
}
