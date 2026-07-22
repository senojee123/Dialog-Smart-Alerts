import { useState } from 'react'
import { Plus, MapPin, Copy } from 'lucide-react'
import { MapContainer, TileLayer, Marker, Popup, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { useApi } from '../../hooks/useApi.js'
import {
  PageHeader, Btn, Badge, StatusDot, Table, SlideOver,
  Field, Input, Select, SaveBar, ConfirmDialog, ErrorBanner,
} from '../../components/admin/CrudShell.jsx'

const BLANK = {
  name: '', type: 'camera', zone_id: '', use_case_id: '',
  lat: null, lng: null, online: false, api_key: '',
}

const DEVICE_TYPES = ['camera', 'thermal', 'drone', 'pressure_pad', 'acoustic', 'manual']

function MapClickHandler({ onPick }) {
  useMapEvents({ click(e) { onPick(e.latlng) } })
  return null
}

function pinIcon(online) {
  const fill = online ? '#12B76A' : '#667085'
  return L.divIcon({
    html: `<svg viewBox="0 0 24 24" width="22" height="22" fill="${fill}" xmlns="http://www.w3.org/2000/svg">
             <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
           </svg>`,
    className: '', iconSize: [22, 22], iconAnchor: [11, 22],
  })
}

export default function Devices() {
  const { data: devices, loading, error, create, update, remove } = useApi('/api/devices')
  const { data: useCases }  = useApi('/api/use-cases')
  const { data: zones }     = useApi('/api/zones')

  const [slideOpen, setSlideOpen]   = useState(false)
  const [editing, setEditing]       = useState(null)
  const [form, setForm]             = useState(BLANK)
  const [saving, setSaving]         = useState(false)
  const [saveError, setSaveError]   = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)
  const [viewMode, setViewMode]     = useState('table')
  const [pickingMap, setPickingMap] = useState(false)

  function openNew()     { setEditing(null); setForm(BLANK); setSaveError(null); setSlideOpen(true) }
  function openEdit(dev) { setEditing(dev);  setForm({ ...dev }); setSaveError(null); setSlideOpen(true) }
  function close()       { setSlideOpen(false); setPickingMap(false) }
  function set(k, v)     { setForm(f => ({ ...f, [k]: v })) }

  function handleMapPick(latlng) {
    set('lat', parseFloat(latlng.lat.toFixed(6)))
    set('lng', parseFloat(latlng.lng.toFixed(6)))
    setPickingMap(false)
  }

  async function save() {
    if (!form.name.trim())     { setSaveError('Name is required'); return }
    if (!form.use_case_id)     { setSaveError('Use Case is required'); return }
    if (!form.zone_id)         { setSaveError('Zone is required'); return }
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

  function copyKey(key) {
    navigator.clipboard?.writeText(key).catch(() => {})
  }

  const filteredZones = zones.filter(z => !form.use_case_id || z.use_case_id === form.use_case_id)

  const columns = [
    { key: 'name', label: 'Device',
      render: row => (
        <div>
          <div className="font-medium text-ink">{row.name}</div>
          <div className="text-xs text-ink-muted capitalize">{row.type}</div>
        </div>
      ),
    },
    { key: 'zone_id', label: 'Zone',
      render: row => {
        const z = zones.find(z => z.id === row.zone_id)
        return <span className="text-xs text-ink-muted">{z?.name || row.zone_id || '—'}</span>
      },
    },
    { key: 'use_case_id', label: 'Use Case',
      render: row => {
        const uc = useCases.find(u => u.id === row.use_case_id)
        return uc
          ? <span className="text-xs font-medium" style={{ color: uc.color }}>{uc.name}</span>
          : <span className="text-xs text-ink-muted">{row.use_case_id || '—'}</span>
      },
    },
    { key: 'online', label: 'Status', render: row => <StatusDot online={row.online} /> },
    { key: 'last_seen', label: 'Last Seen',
      render: row => <span className="text-xs text-ink-muted">{row.last_seen ? row.last_seen.slice(0, 16).replace('T', ' ') : 'Never'}</span> },
    { key: 'api_key', label: 'API Key',
      render: row => (
        <div className="flex items-center gap-1.5">
          <code className="text-xs font-mono text-ink-muted bg-surface px-1.5 py-0.5 rounded">{row.api_key}</code>
          <button onClick={() => copyKey(row.api_key)} className="text-ink-muted hover:text-ink">
            <Copy size={11} />
          </button>
        </div>
      ),
    },
  ]

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHeader
        title="Device Registry"
        description="Camera traps, thermal sensors, drones and other input devices."
        action={
          <div className="flex items-center gap-2">
            <div className="flex border border-line rounded-lg overflow-hidden text-sm">
              <button onClick={() => setViewMode('table')}
                      className={`px-3 py-1.5 ${viewMode === 'table' ? 'bg-brand text-white' : 'text-ink-muted hover:bg-surface-alt'}`}>
                Table
              </button>
              <button onClick={() => setViewMode('map')}
                      className={`px-3 py-1.5 flex items-center gap-1.5 ${viewMode === 'map' ? 'bg-brand text-white' : 'text-ink-muted hover:bg-surface-alt'}`}>
                <MapPin size={13} /> Map
              </button>
            </div>
            <Btn onClick={openNew}><Plus size={14} /> New Device</Btn>
          </div>
        }
      />

      <div className="flex-1 overflow-auto">
        {loading && <p className="px-6 py-4 text-sm text-ink-muted">Loading…</p>}
        {error   && <p className="px-6 py-4 text-sm text-sev-critical">{error}</p>}

        {!loading && viewMode === 'table' && (
          <Table columns={columns} rows={devices} onEdit={openEdit} onDelete={setConfirmDel}
                 emptyMessage="No devices registered. Add a device to start ingesting events." />
        )}

        {!loading && viewMode === 'map' && (
          <MapContainer center={[6.35, 81.42]} zoom={11} style={{ height: '100%', width: '100%' }}>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {devices.map(dev => dev.lat && dev.lng ? (
              <Marker key={dev.id} position={[dev.lat, dev.lng]} icon={pinIcon(dev.online)}>
                <Popup>
                  <div className="text-xs min-w-[160px]">
                    <div className="font-semibold">{dev.name}</div>
                    <div className="text-gray-500 capitalize">{dev.type} · {dev.online ? 'Online' : 'Offline'}</div>
                    <button onClick={() => { openEdit(dev) }}
                            className="mt-2 text-blue-600 underline text-xs">Edit</button>
                  </div>
                </Popup>
              </Marker>
            ) : null)}
          </MapContainer>
        )}
      </div>

      <SlideOver open={slideOpen} onClose={close} title={editing ? 'Edit Device' : 'Register Device'}>
        <div className="space-y-4">
          <ErrorBanner error={saveError} />

          <Field label="Device Name" required>
            <Input value={form.name} onChange={e => set('name', e.target.value)}
                   placeholder="e.g. Camera Trap – B43 North Gate" />
          </Field>

          <Field label="Type" required>
            <Select value={form.type} onChange={e => set('type', e.target.value)}>
              {DEVICE_TYPES.map(t => (
                <option key={t} value={t} className="capitalize">{t.replace('_', ' ')}</option>
              ))}
            </Select>
          </Field>
          {editing && (
            <Field label="Status" hint="Driven automatically by device heartbeats — not editable here.">
              <StatusDot online={form.online} />
            </Field>
          )}

          <Field label="Use Case" required>
            <Select value={form.use_case_id} onChange={e => { set('use_case_id', e.target.value); set('zone_id', '') }}>
              <option value="">Select use case…</option>
              {useCases.map(uc => <option key={uc.id} value={uc.id}>{uc.name}</option>)}
            </Select>
          </Field>

          <Field label="Zone" required>
            <Select value={form.zone_id} onChange={e => set('zone_id', e.target.value)}
                    disabled={!form.use_case_id}>
              <option value="">Select zone…</option>
              {filteredZones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}
            </Select>
          </Field>

          <Field label="Location (lat, lng)" hint="Click 'Pick on map' to set coordinates visually">
            <div className="flex items-center gap-2">
              <Input value={form.lat ?? ''} onChange={e => set('lat', parseFloat(e.target.value))}
                     placeholder="Lat" type="number" step="0.0001" className="flex-1" />
              <Input value={form.lng ?? ''} onChange={e => set('lng', parseFloat(e.target.value))}
                     placeholder="Lng" type="number" step="0.0001" className="flex-1" />
            </div>
            <button onClick={() => setPickingMap(p => !p)}
                    className="mt-2 text-xs text-brand hover:underline flex items-center gap-1">
              <MapPin size={11} />
              {pickingMap ? 'Click the map below to pick location' : 'Pick on map'}
            </button>
          </Field>

          {pickingMap && (
            <div className="rounded-lg overflow-hidden border border-line" style={{ height: 240 }}>
              <MapContainer center={[6.35, 81.42]} zoom={11} style={{ height: '100%' }}>
                <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                <MapClickHandler onPick={handleMapPick} />
                {form.lat && form.lng && (
                  <Marker position={[form.lat, form.lng]} icon={pinIcon(true)} />
                )}
              </MapContainer>
            </div>
          )}

          <Field label="API Key" hint="Auto-generated if left blank. Devices use this to authenticate events.">
            <Input value={form.api_key || ''} onChange={e => set('api_key', e.target.value)}
                   placeholder="Auto-generated on save" />
          </Field>

          <SaveBar onSave={save} onCancel={close} saving={saving} />
        </div>
      </SlideOver>

      <ConfirmDialog
        open={!!confirmDel}
        message={`Delete device "${confirmDel?.name}"? Events from this device will no longer be processed.`}
        onConfirm={async () => { await remove(confirmDel.id); setConfirmDel(null) }}
        onCancel={() => setConfirmDel(null)}
      />
    </div>
  )
}
