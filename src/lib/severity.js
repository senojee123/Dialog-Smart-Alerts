export const SEVERITY = {
  CRITICAL: 'CRITICAL',
  HIGH:     'HIGH',
  MEDIUM:   'MEDIUM',
  LOW:      'LOW',
}

export const SEV_META = {
  CRITICAL: { bg: '#D92D20', text: 'white', icon: 'Siren',         label: 'Critical', order: 0 },
  HIGH:     { bg: '#F2841C', text: 'white', icon: 'AlertTriangle', label: 'High',     order: 1 },
  MEDIUM:   { bg: '#F5B70A', text: '#1A1A1A', icon: 'AlertCircle', label: 'Medium',   order: 2 },
  LOW:      { bg: '#12B76A', text: 'white', icon: 'Info',           label: 'Low',      order: 3 },
}

export function sevOrder(severity) {
  return SEV_META[severity]?.order ?? 99
}
