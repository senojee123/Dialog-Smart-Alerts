import { useEffect, useMemo } from 'react'
import { Wifi, WifiOff, Camera, Thermometer, Plane, Radio, Activity } from 'lucide-react'
import { useApi } from '../hooks/useApi.js'
import { relativeTime } from '../lib/format.js'

const TYPE_ICON = {
  camera: Camera, thermal: Thermometer, drone: Plane,
  acoustic: Radio, pressure_pad: Activity, manual: Activity,
}

export default function Devices() {
  const { data: devices, loading, fetchAll } = useApi('/api/devices')
  const { data: zones } = useApi('/api/zones')

  // Poll so heartbeats/online status stay fresh
  useEffect(() => {
    const t = setInterval(fetchAll, 10000)
    return () => clearInterval(t)
  }, [fetchAll])

  const zoneName = useMemo(() => {
    const m = {}; zones.forEach(z => { m[z.id] = z.name }); return m
  }, [zones])

  const onlineCount = devices.filter(d => d.online).length

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold text-ink">Devices</h1>
          <p className="text-sm text-ink-muted mt-0.5">
            {onlineCount}/{devices.length} online · live from device registry
          </p>
        </div>
      </div>

      {loading && devices.length === 0 && <p className="text-sm text-ink-muted">Loading…</p>}

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-surface-alt border-b border-line">
            {['Device ID', 'Name', 'Type', 'Zone', 'Last Seen', 'Status'].map(h => (
              <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {devices.map(d => {
            const Icon = TYPE_ICON[d.type] || Camera
            return (
              <tr key={d.id} className="hover:bg-surface">
                <td className="px-4 py-3 font-mono text-xs text-ink-muted">{d.id}</td>
                <td className="px-4 py-3 text-ink">{d.name}</td>
                <td className="px-4 py-3 text-ink-muted">
                  <span className="inline-flex items-center gap-1.5 capitalize">
                    <Icon size={13} /> {(d.type || '').replace('_', ' ')}
                  </span>
                </td>
                <td className="px-4 py-3 text-ink-muted">{zoneName[d.zone_id] || d.zone_id || '—'}</td>
                <td className="px-4 py-3 text-ink-muted">{d.last_seen ? relativeTime(d.last_seen) : 'Never'}</td>
                <td className="px-4 py-3">
                  <span className={`flex items-center gap-1.5 text-xs font-medium ${d.online ? 'text-sev-low' : 'text-sev-critical'}`}>
                    {d.online ? <Wifi size={13} /> : <WifiOff size={13} />}
                    {d.online ? 'Online' : 'Offline'}
                  </span>
                </td>
              </tr>
            )
          })}
          {!loading && devices.length === 0 && (
            <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-muted text-sm">
              No devices registered. Add them in Configuration → Devices.
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
