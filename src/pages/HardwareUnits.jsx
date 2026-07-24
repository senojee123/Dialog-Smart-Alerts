import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi.js'
import StatusBadge from '../components/common/StatusBadge.jsx'
import ConfirmDialog from '../components/common/ConfirmDialog.jsx'
import { relativeTime } from '../lib/format.js'
import { Power, PowerOff } from 'lucide-react'

export default function HardwareUnits() {
  const { data: devices, loading, update, fetchAll } = useApi('/api/devices')
  const { data: zones } = useApi('/api/zones')
  const [confirm, setConfirm] = useState(null)

  const zoneMap = useMemo(() => {
    const m = {}
    if (zones) {
      zones.forEach(z => { m[z.id] = z.name })
    }
    return m
  }, [zones])

  const units = useMemo(() => {
    return (devices || [])
      .filter(d => d.type === 'siren' || d.type === 'gate')
      .map(d => ({
        id: d.id,
        name: d.name,
        zone: zoneMap[d.zone_id] || d.zone_id || 'Yala Corridor',
        state: d.state || (d.online ? 'OFF' : 'OFFLINE'),
        last_seen: d.last_seen || d.data?.last_seen || new Date().toISOString()
      }))
  }, [devices, zoneMap])

  async function handleOverride(id, targetState) {
    const rawDev = devices.find(d => d.id === id)
    if (rawDev) {
      // Put updated state back into device document
      await update(id, { ...rawDev, state: targetState })
      fetchAll()
    }
    setConfirm(null)
  }

  return (
    <div className="p-6 max-w-4xl bg-white border border-[#EAECF0] rounded-xl shadow-sm space-y-4 my-6 mx-auto">
      <div>
        <h1 className="text-xl font-semibold text-ink">Hardware Units</h1>
        <p className="text-xs text-ink-muted mt-0.5">
          Live monitoring and manual overrides for sirens and gate units deployed on corridor networks.
        </p>
      </div>

      {loading && units.length === 0 ? (
        <p className="text-sm text-ink-muted">Loading hardware units...</p>
      ) : units.length === 0 ? (
        <div className="p-6 text-center border border-dashed border-[#EAECF0] rounded-lg">
          <p className="text-xs text-ink-muted">No hardware units registered yet.</p>
          <p className="text-[11px] text-ink-subtle mt-0.5">Go to Device Registry under Configuration to add sirens or gates.</p>
        </div>
      ) : (
        <table className="w-full text-sm border-collapse border border-[#EAECF0] rounded-lg overflow-hidden">
          <thead>
            <tr className="bg-surface-alt border-b border-[#EAECF0] text-ink-muted font-bold text-[11px] uppercase tracking-wider text-left">
              {['Unit ID', 'Name', 'Zone / Location', 'State', 'Last Seen', 'Override Control'].map(h => (
                <th key={h} className="px-4 py-2.5">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#EAECF0]">
            {units.map(u => (
              <tr key={u.id} className="hover:bg-surface-alt/40 transition-colors">
                <td className="px-4 py-3 font-mono text-xs text-ink-muted">{u.id}</td>
                <td className="px-4 py-3 text-ink font-semibold">{u.name}</td>
                <td className="px-4 py-3 text-ink-muted">{u.zone}</td>
                <td className="px-4 py-3"><StatusBadge status={u.state} /></td>
                <td className="px-4 py-3 text-ink-muted font-mono text-xs">{relativeTime(u.last_seen)}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button
                      disabled={u.state === 'ON' || u.state === 'OFFLINE'}
                      onClick={() => setConfirm({ id: u.id, name: u.name, target: 'ON' })}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded border border-[#12B76A] text-[#12B76A] hover:bg-emerald-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      <Power size={11} /> ON
                    </button>
                    <button
                      disabled={u.state !== 'ON' && u.state !== 'MANUAL_OVERRIDE'}
                      onClick={() => setConfirm({ id: u.id, name: u.name, target: 'OFF' })}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded border border-[#D92D20] text-[#D92D20] hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      <PowerOff size={11} /> OFF
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <ConfirmDialog
        open={!!confirm}
        title={`Manual Override — ${confirm?.name}`}
        message={`Set ${confirm?.name} to ${confirm?.target}? This action will override automatic rules and be logged in the system.`}
        confirmLabel={`Turn ${confirm?.target}`}
        danger={confirm?.target === 'OFF'}
        onConfirm={() => handleOverride(confirm.id, confirm.target)}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}
