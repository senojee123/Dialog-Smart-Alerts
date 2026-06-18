import { useState } from 'react'
import { Plus, Phone, Mail, MessageSquare, Trash2 } from 'lucide-react'
import { useApi } from '../../hooks/useApi.js'
import {
  PageHeader, Btn, Badge, StatusDot, Table, SlideOver,
  Field, Input, Select, SaveBar, ConfirmDialog, ErrorBanner,
} from '../../components/admin/CrudShell.jsx'

const BLANK = { name: '', role: '', org: '', use_case_ids: [], channels: [], on_call: false }

const CHANNEL_TYPES = [
  { value: 'sms',      label: 'SMS',      icon: Phone },
  { value: 'whatsapp', label: 'WhatsApp', icon: MessageSquare },
  { value: 'email',    label: 'Email',    icon: Mail },
]

const CHANNEL_ICONS = { sms: Phone, whatsapp: MessageSquare, email: Mail }

function ChannelBadge({ ch }) {
  const Icon = CHANNEL_ICONS[ch.type] || Phone
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-surface-alt text-ink-muted border border-line">
      <Icon size={10} />
      {ch.address}
    </span>
  )
}

export default function Stakeholders() {
  const { data, loading, error, create, update, remove } = useApi('/api/stakeholders')
  const { data: useCases } = useApi('/api/use-cases')

  const [slideOpen, setSlideOpen]   = useState(false)
  const [editing, setEditing]       = useState(null)
  const [form, setForm]             = useState(BLANK)
  const [saving, setSaving]         = useState(false)
  const [saveError, setSaveError]   = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)
  const [newCh, setNewCh]           = useState({ type: 'sms', address: '', language: 'en' })

  function openNew()  { setEditing(null); setForm({ ...BLANK, channels: [] }); setSaveError(null); setSlideOpen(true) }
  function openEdit(s){ setEditing(s);    setForm({ ...s, channels: [...(s.channels || [])] }); setSaveError(null); setSlideOpen(true) }
  function close()    { setSlideOpen(false) }
  function set(k, v)  { setForm(f => ({ ...f, [k]: v })) }

  function addChannel() {
    if (!newCh.address.trim()) return
    set('channels', [...(form.channels || []), { ...newCh }])
    setNewCh({ type: 'sms', address: '', language: 'en' })
  }

  function removeChannel(idx) {
    set('channels', form.channels.filter((_, i) => i !== idx))
  }

  function toggleUseCase(id) {
    const ids = form.use_case_ids || []
    set('use_case_ids', ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id])
  }

  async function save() {
    if (!form.name.trim()) { setSaveError('Name is required'); return }
    if ((form.channels || []).length === 0) { setSaveError('At least one contact channel is required'); return }
    setSaving(true); setSaveError(null)
    try {
      editing ? await update(editing.id, form) : await create(form)
      close()
    } catch (e) {
      setSaveError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const columns = [
    { key: 'name', label: 'Name',
      render: row => (
        <div>
          <div className="font-medium text-ink">{row.name}</div>
          <div className="text-xs text-ink-muted">{row.role}{row.org ? ` · ${row.org}` : ''}</div>
        </div>
      ),
    },
    { key: 'channels', label: 'Channels',
      render: row => (
        <div className="flex flex-wrap gap-1">
          {(row.channels || []).map((ch, i) => <ChannelBadge key={i} ch={ch} />)}
        </div>
      ),
    },
    { key: 'use_case_ids', label: 'Use Cases',
      render: row => (
        <div className="flex flex-wrap gap-1">
          {(row.use_case_ids || []).map(id => {
            const uc = useCases.find(u => u.id === id)
            return uc
              ? <span key={id} className="text-xs px-2 py-0.5 rounded font-medium"
                      style={{ background: uc.color + '18', color: uc.color }}>{uc.name}</span>
              : <Badge key={id} color="gray">{id}</Badge>
          })}
        </div>
      ),
    },
    { key: 'on_call', label: 'On-call',
      render: row => <Badge color={row.on_call ? 'green' : 'gray'}>{row.on_call ? 'Yes' : 'No'}</Badge> },
  ]

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHeader
        title="Stakeholder Registry"
        description="People and organisations who receive alerts. Each stakeholder can have multiple contact channels."
        action={<Btn onClick={openNew}><Plus size={14} /> New Stakeholder</Btn>}
      />

      <div className="flex-1 overflow-auto">
        {loading && <p className="px-6 py-4 text-sm text-ink-muted">Loading…</p>}
        {error   && <p className="px-6 py-4 text-sm text-sev-critical">{error}</p>}
        {!loading && (
          <Table columns={columns} rows={data} onEdit={openEdit} onDelete={setConfirmDel}
                 emptyMessage="No stakeholders yet. Add contacts to enable notifications." />
        )}
      </div>

      <SlideOver open={slideOpen} onClose={close} title={editing ? 'Edit Stakeholder' : 'New Stakeholder'}>
        <div className="space-y-4">
          <ErrorBanner error={saveError} />

          <Field label="Full Name" required>
            <Input value={form.name} onChange={e => set('name', e.target.value)}
                   placeholder="e.g. Park Warden – Yala" />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Role">
              <Input value={form.role || ''} onChange={e => set('role', e.target.value)}
                     placeholder="Wildlife Officer" />
            </Field>
            <Field label="Organisation">
              <Input value={form.org || ''} onChange={e => set('org', e.target.value)}
                     placeholder="DWC" />
            </Field>
          </div>

          <Field label="On-call Schedule">
            <Select value={form.on_call ? 'true' : 'false'}
                    onChange={e => set('on_call', e.target.value === 'true')}>
              <option value="true">On-call (receives all alerts)</option>
              <option value="false">Off-call (may be skipped by rules)</option>
            </Select>
          </Field>

          {/* Contact channels */}
          <div>
            <div className="text-sm font-medium text-ink mb-2">
              Contact Channels <span className="text-sev-critical">*</span>
            </div>

            {(form.channels || []).length > 0 && (
              <div className="space-y-1.5 mb-3">
                {form.channels.map((ch, i) => {
                  const Icon = CHANNEL_ICONS[ch.type] || Phone
                  return (
                    <div key={i} className="flex items-center gap-2 px-3 py-2 bg-surface rounded-lg border border-line text-sm">
                      <Icon size={13} className="text-ink-muted shrink-0" />
                      <span className="capitalize text-ink-muted text-xs w-16">{ch.type}</span>
                      <span className="text-ink flex-1 font-mono text-xs">{ch.address}</span>
                      <span className="text-xs text-ink-muted">{ch.language}</span>
                      <button onClick={() => removeChannel(i)} className="text-ink-muted hover:text-sev-critical ml-1">
                        <Trash2 size={12} />
                      </button>
                    </div>
                  )
                })}
              </div>
            )}

            <div className="flex items-end gap-2 p-3 bg-surface-alt rounded-lg border border-line">
              <div className="w-28">
                <Select value={newCh.type} onChange={e => setNewCh(c => ({ ...c, type: e.target.value }))}>
                  {CHANNEL_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </Select>
              </div>
              <div className="flex-1">
                <Input value={newCh.address} onChange={e => setNewCh(c => ({ ...c, address: e.target.value }))}
                       placeholder={newCh.type === 'email' ? 'user@example.com' : '+94771234567'}
                       onKeyDown={e => e.key === 'Enter' && addChannel()} />
              </div>
              <div className="w-16">
                <Select value={newCh.language} onChange={e => setNewCh(c => ({ ...c, language: e.target.value }))}>
                  <option value="en">EN</option>
                  <option value="si">SI</option>
                  <option value="ta">TA</option>
                </Select>
              </div>
              <Btn variant="secondary" size="sm" onClick={addChannel}>Add</Btn>
            </div>
          </div>

          {/* Use case assignment */}
          {useCases.length > 0 && (
            <Field label="Assigned Use Cases" hint="This stakeholder receives alerts from selected use cases">
              <div className="space-y-1.5 mt-1">
                {useCases.map(uc => (
                  <label key={uc.id} className="flex items-center gap-2.5 cursor-pointer">
                    <input type="checkbox"
                           checked={(form.use_case_ids || []).includes(uc.id)}
                           onChange={() => toggleUseCase(uc.id)}
                           className="rounded border-line accent-brand" />
                    <span className="text-sm text-ink">{uc.name}</span>
                  </label>
                ))}
              </div>
            </Field>
          )}

          <SaveBar onSave={save} onCancel={close} saving={saving} />
        </div>
      </SlideOver>

      <ConfirmDialog
        open={!!confirmDel}
        message={`Delete stakeholder "${confirmDel?.name}"? They will no longer receive alerts.`}
        onConfirm={async () => { await remove(confirmDel.id); setConfirmDel(null) }}
        onCancel={() => setConfirmDel(null)}
      />
    </div>
  )
}
