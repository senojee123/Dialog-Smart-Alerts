import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { LayerReport } from '../layers/LayerManager';
import { MapStatus } from './MapStatus';

function report(overrides: Partial<LayerReport>): LayerReport {
  return {
    status: 'success',
    count: 0,
    error: null,
    truncated: false,
    refDataRelease: null,
    reason: null,
    ...overrides,
  };
}

describe('MapStatus', () => {
  it('says the map is loading until it is ready', () => {
    render(
      <MapStatus reports={{}} mapReady={false} styleFailed={false} basemapConfigured interaction={null} />,
    );
    expect(screen.getByText('Loading the map…')).toBeInTheDocument();
  });

  it('names a layer that did not load, with what the service said', () => {
    render(
      <MapStatus
        reports={{ devices: report({ status: 'error', error: new Error('gateway timeout') }) }}
        mapReady
        styleFailed={false}
        basemapConfigured
        interaction={null}
      />,
    );
    expect(screen.getByText(/Devices did not load: gateway timeout/)).toBeInTheDocument();
  });

  it('warns when only the first pages are drawn', () => {
    render(
      <MapStatus
        reports={{ settlements: report({ truncated: true, count: 500 }) }}
        mapReady
        styleFailed={false}
        basemapConfigured
        interaction={null}
      />,
    );
    expect(screen.getByText(/Settlements/)).toHaveTextContent('showing the first pages only');
  });

  it('names the reference data release the answers came from, once', () => {
    render(
      <MapStatus
        reports={{
          settlements: report({ refDataRelease: 'ref-2026.09-lka-open' }),
          roads: report({ refDataRelease: 'ref-2026.09-lka-open' }),
        }}
        mapReady
        styleFailed={false}
        basemapConfigured
        interaction={null}
      />,
    );
    expect(screen.getByText('Reference data ref-2026.09-lka-open')).toBeInTheDocument();
  });

  it('says when the basemap is missing or failed, and what the operator is doing', () => {
    const { rerender } = render(
      <MapStatus
        reports={{}}
        mapReady
        styleFailed={false}
        basemapConfigured={false}
        interaction="Click the map to search around a position."
      />,
    );
    expect(screen.getByText(/No basemap configured/)).toBeInTheDocument();
    expect(screen.getByText('Click the map to search around a position.')).toBeInTheDocument();
    rerender(
      <MapStatus reports={{}} mapReady styleFailed basemapConfigured interaction={null} />,
    );
    expect(screen.getByText(/basemap style could not be loaded/)).toBeInTheDocument();
  });

  it('counts the layers that are loading', () => {
    render(
      <MapStatus
        reports={{ a: report({ status: 'loading' }), b: report({ status: 'loading' }) }}
        mapReady
        styleFailed={false}
        basemapConfigured
        interaction={null}
      />,
    );
    expect(screen.getByText('Loading 2 layers…')).toBeInTheDocument();
  });
});
