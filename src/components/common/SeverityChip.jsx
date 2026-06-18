import { Siren, AlertTriangle, AlertCircle, Info } from 'lucide-react'
import { SEV_META } from '../../lib/severity.js'

const ICONS = { Siren, AlertTriangle, AlertCircle, Info }

export default function SeverityChip({ severity, pulse = false, size = 'sm' }) {
  const meta = SEV_META[severity]
  if (!meta) return null

  const Icon = ICONS[meta.icon]
  const padding = size === 'lg' ? 'px-3 py-1.5 text-sm' : 'px-2 py-0.5 text-xs'

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-semibold rounded-md ${padding} ${pulse ? 'critical-pulse' : ''}`}
      style={{ backgroundColor: meta.bg, color: meta.text }}
    >
      {Icon && <Icon size={size === 'lg' ? 14 : 12} />}
      {meta.label}
    </span>
  )
}
