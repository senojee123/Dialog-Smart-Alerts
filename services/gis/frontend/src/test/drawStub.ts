/**
 * A stand-in for the Terra Draw controller: it records what the editor asked of it, and lets a test
 * play the part of the operator by handing a finished shape back.
 */
import { vi } from 'vitest';

import type { DrawMode, DrawPurpose, TerraDrawController } from '../map/editor/useTerraDraw';
import type { Geometry } from '../types/api';

export interface DrawStub extends TerraDrawController {
  readonly calls: { readonly modes: [DrawMode, DrawPurpose | undefined][]; readonly loaded: Geometry[]; readonly removed: string[]; cleared: number };
  /** What `load` should answer; `null` means Terra Draw refused the shape. */
  loadAnswer: string | null;
  /** Called for each shape removed or cleared, as Terra Draw reports the deletion as a change. */
  onRemove: ((id: string) => void) | null;
  /** The ids of the shapes `load` put in, until they are removed or cleared. */
  readonly held: Set<string>;
  /** What `finishedRecently` answers. */
  recentlyFinished: boolean;
}

export function drawStub(
  options: { ready?: boolean; mode?: DrawMode; purpose?: DrawPurpose } = {},
): DrawStub {
  const { ready = true, mode = 'static', purpose = 'geofence' } = options;
  const calls = { modes: [] as [DrawMode, DrawPurpose | undefined][], loaded: [] as Geometry[], removed: [] as string[], cleared: 0 };
  const stub: DrawStub = {
    ready,
    mode,
    purpose,
    drawing: mode !== 'static' && mode !== 'select',
    loadAnswer: 'drawn-1',
    onRemove: null,
    held: new Set<string>(),
    recentlyFinished: false,
    calls,
    setMode: vi.fn((mode: DrawMode, purpose?: DrawPurpose) => {
      calls.modes.push([mode, purpose]);
    }),
    clear: vi.fn(() => {
      calls.cleared += 1;
      const cleared = [...stub.held];
      stub.held.clear();
      for (const id of cleared) {
        stub.onRemove?.(id);
      }
    }),
    load: vi.fn((geometry: Geometry) => {
      calls.loaded.push(geometry);
      if (stub.loadAnswer !== null) {
        stub.held.add(stub.loadAnswer);
      }
      return stub.loadAnswer;
    }),
    remove: vi.fn((id: string) => {
      calls.removed.push(id);
      stub.held.delete(id);
      stub.onRemove?.(id);
    }),
    finishedRecently: vi.fn(() => stub.recentlyFinished),
  };
  return stub;
}
