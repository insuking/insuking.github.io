import { useCallback, useEffect, useRef, useState } from "react";

export interface PolledFetchResult<T> {
  data: T | null;
  error: boolean;
  refetch: () => void;
}

/**
 * Fetches `fetchFn` immediately on mount, then again every `intervalMs`
 * while the component stays mounted, backing item 2 (auto-refresh) across
 * every page. `refetch()` re-runs it on demand, backing item 5's "다시
 * 시도" retry button. A failed poll (background refresh or a manual retry)
 * only flips `error` and leaves the last good `data` on screen - it never
 * blanks a working view because one refresh failed.
 */
export function usePolledFetch<T>(fetchFn: () => Promise<T>, intervalMs: number): PolledFetchResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState(false);
  const [version, setVersion] = useState(0);

  // Keep the latest closure without making it an effect dependency - the
  // caller typically passes a fresh arrow function each render, and
  // restarting the interval every render would mean it never fires.
  // Updated in its own effect (not during render) since writing a ref
  // during render is a React anti-pattern even though this particular
  // write is idempotent.
  const fetchFnRef = useRef(fetchFn);
  useEffect(() => {
    fetchFnRef.current = fetchFn;
  });

  const refetch = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    let cancelled = false;

    function run() {
      fetchFnRef.current()
        .then((result) => {
          if (!cancelled) {
            setData(result);
            setError(false);
          }
        })
        .catch(() => {
          if (!cancelled) setError(true);
        });
    }

    run();
    const interval = setInterval(run, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // `fetchFn` is deliberately excluded - it's read via `fetchFnRef` above
    // so a new arrow-function identity each render doesn't restart the timer.
  }, [intervalMs, version]);

  return { data, error, refetch };
}
