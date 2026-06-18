import { useState } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'

const SEED = [
  { id: 'e1', name: 'Critical Immediate', trigger: 'CRITICAL', delay_s: 0,   contacts: 'All field officers' },
  { id: 'e2', name: 'High 5-min',         trigger: 'HIGH',     delay_s: 300, contacts: 'DWC Officers' },
  { id: 'e3', name: 'Medium 15-min',      trigger: 'MEDIUM',   delay_s: 900, contacts: 'Patrol Officers' },
]

export default function AdminEscalation() {
  const [items, setItems] = useState(SEED)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({ name: '', trigger: 'HIGH', delay_s: 0, contacts: '' })

  function openCreate() { setForm({ name: '', trigger: 'HIGH', delay_s: 0, contacts: '' }); setEditing('new') }
  function openEdit(e)  { setForm({ name: e.name, trigger: e.trigger, delay_s: e.delay_s, contacts: e.contacts }); setEditing(e.id) }
  function save() {
    const entry = { id: editing === 'new' ? `e${Date.now()}` : editing, ...form, delay_s: Number(form.delay_s) }
    setItems(prev => editing === 'new' ? [...prev, entry] : prev.map(x => x.id === editing ? entry : x))
    setEditing(null)
  }

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-xl font-semibold text-ink">Escalation Policies</h1>
        <button onClick={openCreate} className="flex items-center gap-1.5 px-3 py-2 text-sm bg-brand text-white rounded hover:bg-brand-hover">
          <Plus size={14} /> Add
        </button>
      </div>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-surface-alt border-b border-line">
            {['Name', 'Trigger', 'Delay', 'Contacts', ''].map(h => (
              <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.map(e => (
            <tr key={e.id} className="hover:bg-surface">
              <td className="px-4 py-3 font-medium text-ink">{e.name}</td>
              <td className="px-4 py-3 text-ink-muted">{e.trigger}</td>
              <td className="px-4 py-3 text-ink-muted">{e.delay_s === 0 ? 'Immediate' : `${e.delay_s / 60}m`}</td>
              <td className="px-4 py-3 text-ink-muted">{e.contacts}</td>
              <td className="px-4 py-3">
                <div className="flex gap-2">
                  <button onClick={() => openEdit(e)} className="p-1 text-ink-muted hover:text-ink"><Pencil size={14} /></button>
                  <button onClick={() => setItems(prev => prev.filter(x => x.id !== e.id))} className="p-1 text-ink-muted hover:text-sev-critical"><Trash2 size={14} /></button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg p-6 w-96 shadow-lg">
            <h3 className="font-semibold mb-4">{editing === 'new' ? 'Add Policy' : 'Edit Policy'}</h3>
            <div className="space-y-3 text-sm">
              <div><label className="block text-xs text-ink-muted mb-1">Name</label>
                <input className="w-full border border-line rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
              </div>
              <div><label className="block text-xs text-ink-muted mb-1">Trigger severity</label>
                <select className="w-full border border-line rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand" value={form.trigger} onChange={e => setForm(f => ({ ...f, trigger: e.target.value }))}>
                  {['CRITICAL','HIGH','MEDIUM','LOW'].map(s => <option key={s}>{s}</option>)}
                </select>
              </div>
              <div><label className="block text-xs text-ink-muted mb-1">Delay (seconds)</label>
                <input type="number" className="w-full border border-line rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand" value={form.delay_s} onChange={e => setForm(f => ({ ...f, delay_s: e.target.value }))} />
              </div>
              <div><label className="block text-xs text-ink-muted mb-1">Contacts</label>
                <input className="w-full border border-line rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand" value={form.contacts} onChange={e => setForm(f => ({ ...f, contacts: e.target.value }))} />
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
