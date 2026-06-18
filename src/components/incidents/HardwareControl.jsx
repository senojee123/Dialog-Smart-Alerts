import { useState } from 'react'
import { Power, PowerOff } from 'lucide-react'
import StatusBadge from '../common/StatusBadge.jsx'
import ConfirmDialog from '../common/ConfirmDialog.jsx'
import { relativeTime } from '../../lib/format.js'

export default function HardwareControl({ hardware, incidentId, onOverride }) {
  const [confirm, setConfirm] = useState(null)

  if (!hardware?.unit_id) return <p className="text-sm text-ink-muted">No hardware unit assigned.</p>

  const isOn = hardware.state === 'ON' || hardware.state === 'MANUAL_OVERRIDE'

  return (
    <div className="flex items-center justify-between p-3 bg-surface rounded-lg border border-line">
      <div>
        <div className="text-sm font-medium text-ink">{hardware.name}</div>
        <div className="flex items-center gap-2 mt-1">
          <StatusBadge status={hardware.state} />
          {hardware.expires_at && (
            <span className="text-xs text-ink-muted">Expires {relativeTime(hardware.expires_at)}</span>
          )}
        </div>
      </div>

      <div className="flex gap-2">
        <button
          disabled={isOn}
          onClick={() => setConfirm('ON')}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border font-medium
            disabled:opacity-40 disabled:cursor-not-allowed
            border-sev-low text-sev-low hover:bg-sev-low/10"
        >
          <Power size={12} /> ON
        </button>
        <button
          disabled={!isOn}
          onClick={() => setConfirm('OFF')}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border font-medium
            disabled:opacity-40 disabled:cursor-not-allowed
            border-ink-muted text-ink-muted hover:bg-surface-alt"
        >
          <PowerOff size={12} /> OFF
        </button>
      </div>

      <ConfirmDialog
        open={!!confirm}
        title={`Manual override — turn ${confirm}`}
        message={`This will ${confirm === 'ON' ? 'activate' : 'deactivate'} ${hardware.name}. The action is logged and audited.`}
        confirmLabel={`Turn ${confirm}`}
        danger={confirm === 'OFF'}
        onConfirm={() => { onOverride?.(hardware.unit_id, confirm); setConfirm(null) }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}
