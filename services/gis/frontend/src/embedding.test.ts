import { describe, expect, it } from 'vitest';

import { isEmbedded } from './embedding';

describe('embedding', () => {
  it('knows whether it runs in a frame', () => {
    const top = {} as { parent?: unknown };
    top.parent = top;
    expect(isEmbedded(top as unknown as Window)).toBe(false);
    const framed = { parent: {} } as unknown as Window;
    expect(isEmbedded(framed)).toBe(true);
  });
});
