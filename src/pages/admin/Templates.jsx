import { useState } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'

const SEED = [
  { id: 't1', name: 'SMS Critical',   channel: 'sms',   body: '⚠️ CRITICAL: {{object}} detected near {{location}}. Incident {{incident_id}}. Please respond immediately.' },
  { id: 't2', name: 'Email High',     channel: 'email', body: 'A HIGH severity wildlife incident has been detected. Incident ID: {{incident_id}}. Zone: {{zone}}. Object: {{object}}.' },
  { id: 't3', name: 'Push Notify',    channel: 'push',  body: '{{severity}} alert: {{object}} at {{zone}}' },
]

export default function AdminTemplates() {
  const [items, setItems] = useState(SEED)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({ name: '', channel: 'sms', body: '' })

  function openCreate() { setForm({ name: '', channel: 'sms', body: '' }); setEditing('new') }
  function openEdit(t)  { setForm({ name: t.name, channel: t.channel, body: t.body }); setEditing(t.id) }
  function save() {
    const entry = { id: editing === 'new' ? `t${Date.now()}` : editing, ...form }
    setItems(prev => editing === 'new' ? [...prev, entry] : prev.map(x => x.id === editing ? entry : x))
    setEditing(null)
  }

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-xl font-semibold text-ink">Notification Templates</h1>
        <button onClick={openCreate} className="flex items-center gap-1.5 px-3 py-2 text-sm bg-brand text-white rounded hover:bg-brand-hover">
          <Plus size={14} /> Add
        </button>
      </div>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-surface-alt border-b border-line">
            {['Name', 'Channel', 'Body (preview)', ''].map(h => (
              <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.map(t => (
            <tr key={t.id} className="hover:bg-surface">
              <td className="px-4 py-3 font-medium text-ink">{t.name}</td>
              <td className="px-4 py-3"><span className="px-2 py-0.5 bg-surface-alt text-ink-muted text-xs rounded">{t.channel}</span></td>
              <td className="px-4 py-3 text-ink-muted text-xs max-w-xs truncate">{t.body}</td>
              <td className="px-4 py-3">
                <div className="flex gap-2">
                  <button onClick={() => openEdit(t)} className="p-1 text-ink-muted hover:text-ink"><Pencil size={14} /></button>
                  <button onClick={() => setItems(prev => prev.filter(x => x.id !== t.id))} className="p-1 text-ink-muted hover:text-sev-critical"><Trash2 size={14} /></button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg p-6 w-[480px] shadow-lg">
            <h3 className="font-semibold mb-4">{editing === 'new' ? 'Add Template' : 'Edit Template'}</h3>
            <div className="space-y-3 text-sm">
              <div><label className="block text-xs text-ink-muted mb-1">Name</label>
                <input className="w-full border border-line rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
              </div>
              <div><label className="block text-xs text-ink-muted mb-1">Channel</label>
                <select className="w-full border border-line rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand" value={form.channel} onChange={e => setForm(f => ({ ...f, channel: e.target.value }))}>
                  {['sms','email','push','radio'].map(c => <option key={c}>{c}</option>)}
                </select>
              </div>
              <div><label className="block text-xs text-ink-muted mb-1">Body (use <span className="font-mono">{'{{'}</span>variable<span className="font-mono">{'}}'}</span>)</label>
                <textarea className="w-full border border-line rounded px-3 py-2 font-mono focus:outline-none focus:ring-1 focus:ring-brand" rows={4} value={form.body} onChange={e => setForm(f => ({ ...f, body: e.target.value }))} />
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
