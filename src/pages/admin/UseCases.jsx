import { useState } from 'react'
import { Plus, Zap } from 'lucide-react'
import { useApi } from '../../hooks/useApi.js'
import {
  PageHeader, Btn, Badge, Table, SlideOver,
  Field, Input, Textarea, Select, SaveBar, ConfirmDialog, ErrorBanner,
} from '../../components/admin/CrudShell.jsx'

const BLANK = { name: '', description: '', icon: 'alert', color: '#DA1F26', active: true }

export default function UseCases() {
  const { data, loading, error, create, update, remove } = useApi('/api/use-cases')
  const [slideOpen, setSlideOpen]   = useState(false)
  const [editing, setEditing]       = useState(null)
  const [form, setForm]             = useState(BLANK)
  const [saving, setSaving]         = useState(false)
  const [saveError, setSaveError]   = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)

  function openNew()    { setEditing(null); setForm(BLANK); setSaveError(null); setSlideOpen(true) }
  function openEdit(uc) { setEditing(uc);   setForm({ ...uc }); setSaveError(null); setSlideOpen(true) }
  function close()      { setSlideOpen(false) }
  function set(k, v)    { setForm(f => ({ ...f, [k]: v })) }

  async function save() {
    if (!form.name.trim()) { setSaveError('Name is required'); return }
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

  async function confirmDelete() {
    await remove(confirmDel.id)
    setConfirmDel(null)
  }

  const columns = [
    {
      key: 'name', label: 'Name',
      render: row => (
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: row.color || '#DA1F26' }} />
          <span className="font-medium text-ink">{row.name}</span>
        </div>
      ),
    },
    { key: 'description', label: 'Description',
      render: row => <span className="text-ink-muted text-xs line-clamp-1">{row.description || '—'}</span> },
    { key: 'active', label: 'Status',
      render: row => <Badge color={row.active ? 'green' : 'gray'}>{row.active ? 'Active' : 'Inactive'}</Badge> },
    { key: 'created_at', label: 'Created',
      render: row => <span className="text-xs text-ink-muted">{row.created_at ? row.created_at.slice(0, 10) : '—'}</span> },
  ]

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHeader
        title="Use Case Templates"
        description="Define detection scenarios. Each use case groups devices, rules, and stakeholders."
        action={<Btn onClick={openNew}><Plus size={14} /> New Use Case</Btn>}
      />

      {/* Info banner */}
      <div className="mx-6 mt-4 p-4 rounded-lg bg-brand/5 border border-brand/15 flex items-start gap-3 shrink-0">
        <Zap size={16} className="text-brand mt-0.5 shrink-0" />
        <p className="text-sm text-ink-muted">
          A <strong className="text-ink">Use Case</strong> is the top-level container for a detection scenario —
          e.g. "Elephant Detection". Devices, rules, and stakeholders are linked to a use case.
          The rule engine fires only rules that belong to the same use case as the incoming event's device.
        </p>
      </div>

      <div className="flex-1 overflow-auto mt-4">
        {loading && <p className="px-6 text-sm text-ink-muted">Loading…</p>}
        {error   && <p className="px-6 text-sm text-sev-critical">{error}</p>}
        {!loading && (
          <Table
            columns={columns}
            rows={data}
            onEdit={openEdit}
            onDelete={setConfirmDel}
            emptyMessage="No use cases yet. Create one to start configuring the platform."
          />
        )}
      </div>

      <SlideOver open={slideOpen} onClose={close} title={editing ? 'Edit Use Case' : 'New Use Case'}>
        <div className="space-y-4">
          <ErrorBanner error={saveError} />

          <Field label="Name" required>
            <Input value={form.name} onChange={e => set('name', e.target.value)}
                   placeholder="e.g. Elephant Detection – Road Corridor" />
          </Field>

          <Field label="Description">
            <Textarea value={form.description || ''} onChange={e => set('description', e.target.value)}
                      placeholder="Describe what this use case monitors and responds to." />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Accent Colour" hint="Shown on cards and badges">
              <div className="flex items-center gap-2">
                <input type="color" value={form.color || '#DA1F26'} onChange={e => set('color', e.target.value)}
                       className="w-10 h-9 rounded border border-line cursor-pointer p-0.5" />
                <Input value={form.color || ''} onChange={e => set('color', e.target.value)}
                       placeholder="#DA1F26" className="flex-1" />
              </div>
            </Field>

            <Field label="Status">
              <Select value={form.active ? 'true' : 'false'}
                      onChange={e => set('active', e.target.value === 'true')}>
                <option value="true">Active</option>
                <option value="false">Inactive</option>
              </Select>
            </Field>
          </div>

          <SaveBar onSave={save} onCancel={close} saving={saving} />
        </div>
      </SlideOver>

      <ConfirmDialog
        open={!!confirmDel}
        message={`Delete use case "${confirmDel?.name}"? This cannot be undone. Devices and rules linked to this use case will not be automatically removed.`}
        onConfirm={confirmDelete}
        onCancel={() => setConfirmDel(null)}
      />
    </div>
  )
}
