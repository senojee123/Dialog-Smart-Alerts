import { useState } from 'react'
import { Plus, Copy, ExternalLink } from 'lucide-react'
import { useApi } from '../../hooks/useApi.js'
import {
  PageHeader, Btn, Badge, Table, SlideOver,
  Field, Input, SaveBar, ConfirmDialog, ErrorBanner,
} from '../../components/admin/CrudShell.jsx'

const BLANK = { id: '', name: '', zone_ids: [], station_ids: [] }

export default function KioskDisplays() {
  const { data, loading, error, create, update, remove } = useApi('/api/kiosks')
  const { data: zones } = useApi('/api/zones')

  const [slideOpen, setSlideOpen]   = useState(false)
  const [editing, setEditing]       = useState(null)
  const [form, setForm]             = useState(BLANK)
  const [saving, setSaving]         = useState(false)
  const [saveError, setSaveError]   = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)

  function openNew()  { setEditing(null); setForm(BLANK); setSaveError(null); setSlideOpen(true) }
  function openEdit(k){ setEditing(k);    setForm({ ...BLANK, ...k, zone_ids: [...(k.zone_ids || [])] }); setSaveError(null); setSlideOpen(true) }
  function close()    { setSlideOpen(false) }
  function set(k, v)  { setForm(f => ({ ...f, [k]: v })) }

  function toggleZone(id) {
    const ids = form.zone_ids || []
    set('zone_ids', ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id])
  }

  function copyUrl(id) {
    const url = `${window.location.origin}/device/${id}`
    navigator.clipboard?.writeText(url).catch(() => {})
  }

  async function save() {
    if (!editing && !form.id.trim()) { setSaveError('Device ID is required — this is the exact id the Pi will use in its URL (e.g. "pi-001")'); return }
    if (!form.name.trim())           { setSaveError('Display name is required'); return }
    if ((form.zone_ids || []).length === 0) { setSaveError('Select at least one zone for this display to watch'); return }
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
    { key: 'id', label: 'Device ID',
      render: row => <code className="text-xs font-mono text-ink-muted bg-surface px-1.5 py-0.5 rounded">{row.id}</code> },
    { key: 'name', label: 'Display Name',
      render: row => <span className="font-medium text-ink">{row.name}</span> },
    { key: 'zone_ids', label: 'Watching Zones',
      render: row => (
        <div className="flex flex-wrap gap-1">
          {(row.zone_ids || []).length === 0
            ? <span className="text-xs text-ink-muted">—</span>
            : row.zone_ids.map(id => {
                const z = zones.find(z => z.id === id)
                return <Badge key={id} color="blue">{z?.name || id}</Badge>
              })}
        </div>
      ) },
    { key: 'url', label: 'Display URL',
      render: row => (
        <div className="flex items-center gap-1.5">
          <a href={`/device/${row.id}`} target="_blank" rel="noreferrer"
             className="text-xs text-brand hover:underline flex items-center gap-1">
            /device/{row.id} <ExternalLink size={10} />
          </a>
          <button onClick={() => copyUrl(row.id)} title="Copy full URL" className="text-ink-muted hover:text-ink">
            <Copy size={11} />
          </button>
        </div>
      ) },
  ]

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHeader
        title="Displays"
        description="Raspberry Pi / big-screen display units. Each one watches a set of zones and shows a full-screen alert when an incident opens there."
        action={<Btn onClick={openNew}><Plus size={14} /> New Display</Btn>}
      />

      <div className="flex-1 overflow-auto">
        {loading && <p className="px-6 py-4 text-sm text-ink-muted">Loading…</p>}
        {error   && <p className="px-6 py-4 text-sm text-sev-critical">{error}</p>}
        {!loading && (
          <Table columns={columns} rows={data} onEdit={openEdit} onDelete={setConfirmDel}
                 emptyMessage="No displays registered yet. Add one to point a physical screen at this platform." />
        )}
      </div>

      <SlideOver open={slideOpen} onClose={close} title={editing ? 'Edit Display' : 'New Display'}>
        <div className="space-y-4">
          <ErrorBanner error={saveError} />

          <Field label="Device ID" required
                 hint={editing
                   ? 'Not editable after creation — the display\'s URL is pinned to this id.'
                   : 'Exactly what the display will use in its URL, e.g. "pi-001" → /device/pi-001. Choose it once; it cannot be changed later.'}>
            <Input value={form.id} disabled={!!editing}
                   onChange={e => set('id', e.target.value.trim())}
                   placeholder="pi-001" />
          </Field>

          <Field label="Display Name" required>
            <Input value={form.name} onChange={e => set('name', e.target.value)}
                   placeholder="e.g. Pi Display – Kataragama Checkpoint" />
          </Field>

          <Field label="Watching Zones" required hint="This display shows an alert when any incident opens in one of these zones">
            <div className="space-y-1.5 mt-1">
              {zones.map(z => (
                <label key={z.id} className="flex items-center gap-2.5 cursor-pointer">
                  <input type="checkbox"
                         checked={(form.zone_ids || []).includes(z.id)}
                         onChange={() => toggleZone(z.id)}
                         className="rounded border-line accent-brand" />
                  <span className="text-sm text-ink">{z.name}</span>
                </label>
              ))}
              {zones.length === 0 && <p className="text-xs text-ink-muted">No zones configured yet.</p>}
            </div>
          </Field>

          {editing && (
            <Field label="Display URL">
              <div className="flex items-center gap-2">
                <code className="text-xs font-mono text-ink-muted bg-surface px-2 py-1.5 rounded flex-1">
                  {window.location.origin}/device/{editing.id}
                </code>
                <Btn type="button" variant="secondary" size="sm" onClick={() => copyUrl(editing.id)}>
                  <Copy size={12} /> Copy
                </Btn>
              </div>
            </Field>
          )}

          <SaveBar onSave={save} onCancel={close} saving={saving} />
        </div>
      </SlideOver>

      <ConfirmDialog
        open={!!confirmDel}
        message={`Delete display "${confirmDel?.name}" (${confirmDel?.id})? The physical screen will show a registry error until re-registered.`}
        onConfirm={async () => { await remove(confirmDel.id); setConfirmDel(null) }}
        onCancel={() => setConfirmDel(null)}
      />
    </div>
  )
}
