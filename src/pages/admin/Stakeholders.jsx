import { useState } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'

const SEED = [
  { id: 's1', name: 'Nuwan Perera',    role: 'Field Officer', channels: ['sms', 'push'] },
  { id: 's2', name: 'Chamara Silva',   role: 'DWC Officer',   channels: ['email', 'sms'] },
  { id: 's3', name: 'Priya Wijesinghe', role: 'Village Officer', channels: ['sms'] },
]

export default function AdminStakeholders() {
  const [items, setItems] = useState(SEED)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({ name: '', role: '', channels: '' })

  function openCreate() { setForm({ name: '', role: '', channels: '' }); setEditing('new') }
  function openEdit(s)  { setForm({ name: s.name, role: s.role, channels: s.channels.join(', ') }); setEditing(s.id) }

  function save() {
    const entry = { id: editing === 'new' ? `s${Date.now()}` : editing, name: form.name, role: form.role, channels: form.channels.split(',').map(c => c.trim()).filter(Boolean) }
    setItems(prev => editing === 'new' ? [...prev, entry] : prev.map(s => s.id === editing ? entry : s))
    setEditing(null)
  }

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-xl font-semibold text-ink">Stakeholders</h1>
        <button onClick={openCreate} className="flex items-center gap-1.5 px-3 py-2 text-sm bg-brand text-white rounded hover:bg-brand-hover">
          <Plus size={14} /> Add
        </button>
      </div>

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-surface-alt border-b border-line">
            {['Name', 'Role', 'Channels', ''].map(h => (
              <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.map(s => (
            <tr key={s.id} className="hover:bg-surface">
              <td className="px-4 py-3 font-medium text-ink">{s.name}</td>
              <td className="px-4 py-3 text-ink-muted">{s.role}</td>
              <td className="px-4 py-3 text-ink-muted">{s.channels.join(', ')}</td>
              <td className="px-4 py-3">
                <div className="flex gap-2">
                  <button onClick={() => openEdit(s)} className="p-1 text-ink-muted hover:text-ink"><Pencil size={14} /></button>
                  <button onClick={() => setItems(prev => prev.filter(x => x.id !== s.id))} className="p-1 text-ink-muted hover:text-sev-critical"><Trash2 size={14} /></button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg p-6 w-96 shadow-lg">
            <h3 className="font-semibold mb-4">{editing === 'new' ? 'Add Stakeholder' : 'Edit Stakeholder'}</h3>
            <div className="space-y-3">
              <Field label="Name"     value={form.name}     onChange={v => setForm(f => ({ ...f, name: v }))} />
              <Field label="Role"     value={form.role}     onChange={v => setForm(f => ({ ...f, role: v }))} />
              <Field label="Channels (comma-separated)" value={form.channels} onChange={v => setForm(f => ({ ...f, channels: v }))} />
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

function Field({ label, value, onChange }) {
  return (
    <div>
      <label className="block text-xs text-ink-muted mb-1">{label}</label>
      <input
        className="w-full border border-line rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
        value={value}
        onChange={e => onChange(e.target.value)}
      />
    </div>
  )
}
