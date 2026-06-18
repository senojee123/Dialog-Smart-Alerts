import { useState } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import SeverityChip from '../../components/common/SeverityChip.jsx'

const SEED = [
  { id: 'r1', name: 'Road Proximity Alert', severity: 'CRITICAL', condition: '{"distance_to_road_m":{"lte":50}}',  enabled: true },
  { id: 'r2', name: 'Village Buffer Alert',  severity: 'HIGH',     condition: '{"zone_type":"village_buffer"}',    enabled: true },
  { id: 'r3', name: 'Unconfirmed Detection', severity: 'MEDIUM',   condition: '{"ai_confirmed":false}',            enabled: true },
  { id: 'r4', name: 'Wildlife Activity Log', severity: 'LOW',      condition: '{"object":"deer"}',                 enabled: false },
]

export default function AdminRules() {
  const [rules, setRules] = useState(SEED)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({ name: '', severity: 'MEDIUM', condition: '{}', enabled: true })
  const [jsonError, setJsonError] = useState('')

  function openCreate() { setForm({ name: '', severity: 'MEDIUM', condition: '{}', enabled: true }); setJsonError(''); setEditing('new') }
  function openEdit(r)  { setForm({ name: r.name, severity: r.severity, condition: r.condition, enabled: r.enabled }); setJsonError(''); setEditing(r.id) }

  function save() {
    try { JSON.parse(form.condition) } catch { setJsonError('Invalid JSON'); return }
    const entry = { id: editing === 'new' ? `r${Date.now()}` : editing, ...form }
    setRules(prev => editing === 'new' ? [...prev, entry] : prev.map(r => r.id === editing ? entry : r))
    setEditing(null)
  }

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-xl font-semibold text-ink">Rules</h1>
        <button onClick={openCreate} className="flex items-center gap-1.5 px-3 py-2 text-sm bg-brand text-white rounded hover:bg-brand-hover">
          <Plus size={14} /> Add Rule
        </button>
      </div>

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-surface-alt border-b border-line">
            {['Name', 'Severity', 'Condition', 'Enabled', ''].map(h => (
              <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rules.map(r => (
            <tr key={r.id} className="hover:bg-surface">
              <td className="px-4 py-3 font-medium text-ink">{r.name}</td>
              <td className="px-4 py-3"><SeverityChip severity={r.severity} /></td>
              <td className="px-4 py-3 font-mono text-xs text-ink-muted max-w-[200px] truncate">{r.condition}</td>
              <td className="px-4 py-3">
                <button
                  onClick={() => setRules(prev => prev.map(x => x.id === r.id ? { ...x, enabled: !x.enabled } : x))}
                  className={`w-9 h-5 rounded-full transition-colors ${r.enabled ? 'bg-sev-low' : 'bg-line'}`}
                >
                  <span className={`block w-4 h-4 rounded-full bg-white shadow transition-transform mx-0.5 ${r.enabled ? 'translate-x-4' : ''}`} />
                </button>
              </td>
              <td className="px-4 py-3">
                <div className="flex gap-2">
                  <button onClick={() => openEdit(r)} className="p-1 text-ink-muted hover:text-ink"><Pencil size={14} /></button>
                  <button onClick={() => setRules(prev => prev.filter(x => x.id !== r.id))} className="p-1 text-ink-muted hover:text-sev-critical"><Trash2 size={14} /></button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg p-6 w-[480px] shadow-lg">
            <h3 className="font-semibold mb-4">{editing === 'new' ? 'Add Rule' : 'Edit Rule'}</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-ink-muted mb-1">Name</label>
                <input className="w-full border border-line rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
              </div>
              <div>
                <label className="block text-xs text-ink-muted mb-1">Severity</label>
                <select className="w-full border border-line rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand" value={form.severity} onChange={e => setForm(f => ({ ...f, severity: e.target.value }))}>
                  {['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(s => <option key={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-ink-muted mb-1">Condition (JSON)</label>
                <textarea
                  className={`w-full border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-brand ${jsonError ? 'border-sev-critical' : 'border-line'}`}
                  rows={4}
                  value={form.condition}
                  onChange={e => { setForm(f => ({ ...f, condition: e.target.value })); setJsonError('') }}
                />
                {jsonError && <p className="text-xs text-sev-critical mt-1">{jsonError}</p>}
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => setEditing(null)} className="px-3 py-1.5 text-sm border border-line rounded">Cancel</button>
              <button onClick={save} className="px-3 py-1.5 text-sm bg-brand text-white rounded hover:bg-brand-hover">Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
