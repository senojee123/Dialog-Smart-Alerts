import { MOCK_DEVICES } from '../mock/incidents.js'
import { relativeTime } from '../lib/format.js'
import { Wifi, WifiOff } from 'lucide-react'

export default function Devices() {
  return (
    <div className="p-6 max-w-4xl">
      <h1 className="text-xl font-semibold text-ink mb-4">Devices</h1>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-surface-alt border-b border-line">
            {['Device ID', 'Name', 'Zone', 'Last Heartbeat', 'Status'].map(h => (
              <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {MOCK_DEVICES.map(d => (
            <tr key={d.id} className="hover:bg-surface">
              <td className="px-4 py-3 font-mono text-xs text-ink-muted">{d.id}</td>
              <td className="px-4 py-3 text-ink">{d.name}</td>
              <td className="px-4 py-3 text-ink-muted">{d.zone}</td>
              <td className="px-4 py-3 text-ink-muted">{relativeTime(d.last_heartbeat)}</td>
              <td className="px-4 py-3">
                <span className={`flex items-center gap-1.5 text-xs font-medium ${d.online ? 'text-sev-low' : 'text-sev-critical'}`}>
                  {d.online ? <Wifi size={13} /> : <WifiOff size={13} />}
                  {d.online ? 'Online' : 'Offline'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
