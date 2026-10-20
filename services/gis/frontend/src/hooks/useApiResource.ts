import { useCallback, useEffect, useState } from 'react';

export type ResourceState<T> =
  | { readonly status: 'loading'; readonly data: T | null; readonly error: null }
  | { readonly status: 'success'; readonly data: T; readonly error: null }
  | { readonly status: 'error'; readonly data: T | null; readonly error: Error };

export interface UseApiResourceOptions {
  /** Re-run the loader on this interval (ms). Omit for a one-off load. */
  readonly pollIntervalMs?: number;
}

/**
 * Load a resource with cancellation. Previous data stays visible while a refresh is in flight or
 * after a failed refresh, so the UI does not flicker on every poll.
 *
 * `loader` must be stable (a `useCallback` over what it reads): it is a dependency of the load, so a new
 * one re-reads the resource - which is what makes a changed tenant or API client take effect.
 */
export function useApiResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  options: UseApiResourceOptions = {},
): ResourceState<T> & { readonly refresh: () => void } {
  const { pollIntervalMs } = options;
  const [state, setState] = useState<ResourceState<T>>({ status: 'loading', data: null, error: null });
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    // The next poll is scheduled only after this load settles, so slow responses never overlap.
    const scheduleNext = () => {
      if (pollIntervalMs !== undefined && !controller.signal.aborted) {
        timer = setTimeout(() => {
          setGeneration((value) => value + 1);
        }, pollIntervalMs);
      }
    };

    loader(controller.signal).then(
      (data) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({ status: 'success', data, error: null });
        scheduleNext();
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        const normalised = error instanceof Error ? error : new Error(String(error));
        setState((previous) => ({ status: 'error', data: previous.data, error: normalised }));
        scheduleNext();
      },
    );

    return () => {
      controller.abort();
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
    // The loader is a dependency: a host that changes the tenant or the API client passes a new one, and
    // the resource has to be read again rather than keeping the previous tenant's answer. Callers wrap
    // theirs in `useCallback`, so it changes only when what it reads changes.
  }, [loader, generation, pollIntervalMs]);

  const refresh = useCallback(() => {
    setGeneration((value) => value + 1);
  }, []);

  return { ...state, refresh };
}
