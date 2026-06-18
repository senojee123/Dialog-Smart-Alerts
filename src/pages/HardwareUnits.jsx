import { useState } from 'react'
import { MOCK_HARDWARE } from '../mock/incidents.js'
import StatusBadge from '../components/common/StatusBadge.jsx'
import ConfirmDialog from '../components/common/ConfirmDialog.jsx'
import { relativeTime } from '../lib/format.js'
import { Power, PowerOff } from 'lucide-react'

export default function HardwareUnits() {
  const [units, setUnits] = useState(MOCK_HARDWARE)
  const [confirm, setConfirm] = useState(null)

  function handleOverride(id, state) {
    setUnits(prev => prev.map(u => u.id === id ? { ...u, state } : u))
    setConfirm(null)
  }

  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-xl font-semibold text-ink mb-4">Hardware Units</h1>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-surface-alt border-b border-line">
            {['Unit', 'Name', 'Zone', 'State', 'Last Seen', 'Override'].map(h => (
              <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {units.map(u => (
            <tr key={u.id} className="hover:bg-surface">
              <td className="px-4 py-3 font-mono text-xs text-ink-muted">{u.id}</td>
              <td className="px-4 py-3 text-ink">{u.name}</td>
              <td className="px-4 py-3 text-ink-muted">{u.zone}</td>
              <td className="px-4 py-3"><StatusBadge status={u.state} /></td>
              <td className="px-4 py-3 text-ink-muted">{relativeTime(u.last_seen)}</td>
              <td className="px-4 py-3">
                <div className="flex gap-2">
                  <button
                    disabled={u.state === 'ON' || u.state === 'OFFLINE'}
                    onClick={() => setConfirm({ id: u.id, name: u.name, target: 'ON' })}
                    className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-sev-low text-sev-low hover:bg-sev-low/10 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <Power size={11} /> ON
                  </button>
                  <button
                    disabled={u.state !== 'ON' && u.state !== 'MANUAL_OVERRIDE'}
                    onClick={() => setConfirm({ id: u.id, name: u.name, target: 'OFF' })}
                    className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-ink-muted text-ink-muted hover:bg-surface-alt disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <PowerOff size={11} /> OFF
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <ConfirmDialog
        open={!!confirm}
        title={`Override — ${confirm?.name}`}
        message={`Set ${confirm?.name} to ${confirm?.target}? This is logged.`}
        confirmLabel={`Turn ${confirm?.target}`}
        danger={confirm?.target === 'OFF'}
        onConfirm={() => handleOverride(confirm.id, confirm.target)}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}
