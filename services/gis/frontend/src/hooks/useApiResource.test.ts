import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useApiResource } from './useApiResource';

describe('useApiResource', () => {
  it('loads data and keeps it after a failed refresh', async () => {
    const loader = vi
      .fn<(signal: AbortSignal) => Promise<string>>()
      .mockResolvedValueOnce('first')
      .mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(() => useApiResource(loader));

    await waitFor(() => {
      expect(result.current.status).toBe('success');
    });
    expect(result.current.data).toBe('first');

    act(() => {
      result.current.refresh();
    });
    await waitFor(() => {
      expect(result.current.status).toBe('error');
    });
    expect(result.current.data).toBe('first');
    expect(result.current.error?.message).toBe('offline');
  });

  it('aborts the in-flight request on unmount', async () => {
    let seen: AbortSignal | undefined;
    const loader = vi.fn((signal: AbortSignal) => {
      seen = signal;
      return new Promise<string>(() => undefined);
    });
    const { unmount } = renderHook(() => useApiResource(loader));
    await waitFor(() => {
      expect(loader).toHaveBeenCalled();
    });
    unmount();
    expect(seen?.aborted).toBe(true);
  });

  it('polls on the configured interval after each load completes', async () => {
    vi.useFakeTimers();
    try {
      const loader = vi.fn().mockResolvedValue('ok');
      renderHook(() => useApiResource(loader, { pollIntervalMs: 1000 }));
      for (let tick = 0; tick < 3; tick += 1) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(1000);
        });
      }
      expect(loader).toHaveBeenCalledTimes(4);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('useApiResource, when the loader changes', () => {
  it('reads the resource again, because a new loader reads something else', async () => {
    const first = vi.fn(() => Promise.resolve('wildlife-dept'));
    const second = vi.fn(() => Promise.resolve('forest-dept'));
    const { result, rerender } = renderHook(
      ({ loader }: { loader: () => Promise<string> }) => useApiResource(loader),
      { initialProps: { loader: first as () => Promise<string> } },
    );
    await waitFor(() => {
      expect(result.current.data).toBe('wildlife-dept');
    });
    rerender({ loader: second as () => Promise<string> });
    await waitFor(() => {
      expect(result.current.data).toBe('forest-dept');
    });
    expect(second).toHaveBeenCalledTimes(1);
  });
});
