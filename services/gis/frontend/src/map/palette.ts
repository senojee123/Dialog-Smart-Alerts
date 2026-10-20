/**
 * One palette for the map, so a colour means the same thing in every layer and in the legend.
 *
 * Hues are kept apart in lightness as well as hue, so the layers stay distinguishable for the most
 * common forms of colour blindness and on a projector in a control room.
 */

export const PALETTE = {
  event: '#d92d20',
  eventCluster: '#f04438',
  eventSelected: '#912018',
  device: '#1b3a5c',
  deviceActive: '#1f7a4d',
  deviceInactive: '#9a6700',
  deviceOffline: '#b42318',
  deviceUnknown: '#6b7280',
  fieldOfView: '#2e6db4',
  site: '#4b5563',
  geofence: '#7b2cbf',
  geofenceDraft: '#9a6700',
  geofenceSuspended: '#6b7280',
  settlement: '#8a5a00',
  road: '#5c5c5c',
  water: '#2d7fb8',
  protectedArea: '#1f7a4d',
  riskZone: '#c2410c',
  facility: '#7c3aed',
  adminBoundary: '#64748b',
  tool: '#0f766e',
  draft: '#c026d3',
  serviceArea: '#2e6db4',
} as const;

export type PaletteColour = (typeof PALETTE)[keyof typeof PALETTE];

/** Fill opacities: areas stack, so each one has to stay readable under the next. */
export const FILL_OPACITY = {
  area: 0.18,
  emphasis: 0.3,
  faint: 0.08,
} as const;

/** Device status as the map colours it. `unknown` is what is shown without an external report. */
export const DEVICE_STATE_COLOURS = {
  online: PALETTE.deviceActive,
  degraded: PALETTE.deviceInactive,
  offline: PALETTE.deviceOffline,
  unknown: PALETTE.deviceUnknown,
} as const;

export type DeviceState = keyof typeof DEVICE_STATE_COLOURS;

export const DEVICE_STATES = Object.keys(DEVICE_STATE_COLOURS) as readonly DeviceState[];
