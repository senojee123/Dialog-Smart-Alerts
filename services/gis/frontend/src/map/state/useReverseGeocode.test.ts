import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { apiStub } from '../../test/apiStub';
import { ApiError } from '../../services/apiClient';
import { useReverseGeocode } from './useReverseGeocode';

const POSITION = [80.7513, 8.0342] as const;

describe('useReverseGeocode', () => {
  it('does nothing until it is asked', () => {
    const api = apiStub();
    const { result } = renderHook(() => useReverseGeocode(api, POSITION, false));
    expect(result.current.status).toBe('idle');
    expect(api.reverseGeocode).not.toHaveBeenCalled();
  });

  it('resolves a position into its administrative hierarchy', async () => {
    const api = apiStub();
    const { result } = renderHook(() => useReverseGeocode(api, POSITION, true));
    expect(result.current.status).toBe('loading');
    await waitFor(() => {
      expect(result.current.status).toBe('success');
    });
    expect(result.current.data?.admin.province?.name).toBe('North Central Province');
    expect(api.reverseGeocode).toHaveBeenCalledWith(POSITION, expect.anything());
  });

  it('shows what the service said when it refuses the position', async () => {
    const api = apiStub({
      reverseGeocode: vi.fn(() =>
        Promise.reject(
          new ApiError('refused', {
            status: 422,
            problem: {
              type: 'urn:gis-core-service:problem:invalid_coordinate',
              title: 'Coordinate is not acceptable',
              status: 422,
              detail: 'The position is outside the service area.',
            },
          }),
        ),
      ),
    });
    const { result } = renderHook(() => useReverseGeocode(api, POSITION, true));
    await waitFor(() => {
      expect(result.current.status).toBe('error');
    });
    expect(result.current.error).toBe('The position is outside the service area.');
  });
});
