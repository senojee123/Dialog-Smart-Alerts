import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MAP_LAYERS } from '../layers/layerCatalogue';
import { Legend } from './Legend';

describe('Legend', () => {
  it('explains the layers that are on, and nothing else', () => {
    render(<Legend visible={new Set(['events', 'devices'])} availableLayers={MAP_LAYERS} />);
    expect(screen.getByText('Events')).toBeInTheDocument();
    expect(screen.getByText('Devices')).toBeInTheDocument();
    expect(screen.queryByText('Roads')).not.toBeInTheDocument();
    expect(screen.getByText('Not reported')).toBeInTheDocument();
  });

  it('says so when nothing is shown', () => {
    render(<Legend visible={new Set()} availableLayers={MAP_LAYERS} />);
    expect(screen.getByText('No layers are shown.')).toBeInTheDocument();
  });

  it('leaves out a layer the deployment does not publish', () => {
    render(
      <Legend
        visible={new Set(['events', 'riskZones'])}
        availableLayers={MAP_LAYERS.filter((layer) => layer.id !== 'riskZones')}
      />,
    );
    expect(screen.queryByText('Risk zones')).not.toBeInTheDocument();
  });
});
