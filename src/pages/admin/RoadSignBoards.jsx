import { useState, useRef } from 'react'
import { MapContainer, TileLayer, Marker, Popup, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { Pencil, Trash2, MapPin } from 'lucide-react'
import { useApi } from '../../hooks/useApi.js'
import ConfirmDialog from '../../components/common/ConfirmDialog.jsx'

const EMPTY_FORM = { name: '', road: '', km_marker: '', zone_id: '', lat: '', lng: '', online: true }

function pinIcon(color = '#DA1F26') {
  return L.divIcon({
    html: `<div style="width:14px;height:14px;background:${color};border-radius:50%;border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>`,
    className: '', iconSize: [14, 14], iconAnchor: [7, 7],
  })
}
function placingIcon() {
  return L.divIcon({
    html: `<div style="width:18px;height:18px;background:#DA1F26;border-radius:50%;border:3px solid white;box-shadow:0 0 0 3px rgba(218,31,38,0.4)"></div>`,
    className: '', iconSize: [18, 18], iconAnchor: [9, 9],
  })
}
function MapClickHandler({ placing, onPick }) {
  useMapEvents({ click(e) { if (placing) onPick(e.latlng) } })
  return null
}

export default function AdminRoadSignBoards() {
  const { data: signs, create, update, remove } = useApi('/api/road-signs')
  const { data: zones } = useApi('/api/zones')

  const [placing, setPlacing]       = useState(false)
  const [pendingLatLng, setPending] = useState(null)
  const [editing, setEditing]       = useState(null)   // null | 'new' | sign.id
  const [form, setForm]             = useState(EMPTY_FORM)
  const [confirmDelete, setDelete]  = useState(null)
  const [busy, setBusy]             = useState(false)
  const mapRef = useRef()

  const zoneName = id => zones.find(z => z.id === id)?.name || id

  function startPlace() { setPlacing(true); setPending(null); setEditing(null) }

  function handleMapPick(latlng) {
    setPending(latlng); setPlacing(false)
    setForm({ ...EMPTY_FORM, zone_id: zones[0]?.id || '', lat: latlng.lat.toFixed(5), lng: latlng.lng.toFixed(5) })
    setEditing('new')
  }

  function openEdit(sign) {
    setEditing(sign.id)
    setForm({
      name: sign.name, road: sign.road, km_marker: String(sign.km_marker ?? ''),
      zone_id: sign.zone_id || '', lat: String(sign.lat), lng: String(sign.lng), online: sign.online,
    })
  }

  async function save() {
    const data = {
      name: form.name, road: form.road, km_marker: Number(form.km_marker),
      zone_id: form.zone_id, lat: parseFloat(form.lat), lng: parseFloat(form.lng), online: form.online,
    }
    setBusy(true)
    try {
      if (editing === 'new') await create(data)
      else await update(editing, data)
      setEditing(null); setPending(null)
    } finally { setBusy(false) }
  }

  function cancelEdit() { setEditing(null); setPending(null); setPlacing(false) }

  const mapCursor = placing ? 'crosshair' : 'grab'

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left: table */}
      <div className="w-[420px] shrink-0 flex flex-col border-r border-line overflow-hidden">
        <div className="px-4 py-3 border-b border-line bg-surface flex items-center justify-between">
          <div>
            <h1 className="font-semibold text-ink">Road Sign Boards</h1>
            <p className="text-xs text-ink-muted mt-0.5">{signs.length} boards configured</p>
          </div>
          <button onClick={startPlace}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded font-medium transition-colors
              ${placing ? 'bg-orange text-white' : 'bg-brand text-white hover:bg-brand-hover'}`}>
            <MapPin size={14} />
            {placing ? 'Click map to place…' : 'Add Board'}
          </button>
        </div>

        {placing && (
          <div className="px-4 py-2 bg-orange/10 border-b border-orange/30 text-xs text-orange font-medium">
            Click anywhere on the map to place the new board.
            <button onClick={cancelEdit} className="ml-2 underline">Cancel</button>
          </div>
        )}

        <div className="overflow-y-auto flex-1">
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 bg-surface-alt z-10">
              <tr>
                {['Name', 'Road / km', 'Zone', 'Online', ''].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide border-b border-line whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {signs.map(s => (
                <tr key={s.id} className="hover:bg-surface">
                  <td className="px-3 py-2.5">
                    <div className="font-medium text-ink text-xs">{s.name}</div>
                    <div className="text-xs text-ink-muted font-mono">{s.id}</div>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-ink-muted">
                    <div>{s.road}</div><div>km {s.km_marker}</div>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-ink-muted">{zoneName(s.zone_id)}</td>
                  <td className="px-3 py-2.5">
                    <button onClick={() => update(s.id, { online: !s.online })}
                      className={`w-8 h-4 rounded-full transition-colors ${s.online ? 'bg-sev-low' : 'bg-line'}`}
                      title={s.online ? 'Click to take offline' : 'Click to bring online'}>
                      <span className={`block w-3 h-3 rounded-full bg-white shadow transition-transform mx-0.5 ${s.online ? 'translate-x-4' : ''}`} />
                    </button>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex gap-1">
                      <button onClick={() => openEdit(s)} className="p-1 text-ink-muted hover:text-ink rounded"><Pencil size={12} /></button>
                      <button onClick={() => setDelete(s)} className="p-1 text-ink-muted hover:text-sev-critical rounded"><Trash2 size={12} /></button>
                    </div>
                  </td>
                </tr>
              ))}
              {signs.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-xs text-ink-muted">No boards. Click "Add Board" and place one on the map.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Right: map */}
      <div className="flex-1 relative" style={{ cursor: mapCursor }}>
        <MapContainer ref={mapRef} center={[6.3818, 81.48]} zoom={14} style={{ height: '100%', width: '100%' }} className="z-0">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          <MapClickHandler placing={placing} onPick={handleMapPick} />

          {signs.map(s => (
            <Marker key={s.id} position={[s.lat, s.lng]} icon={pinIcon(s.online ? '#12B76A' : '#667085')}>
              <Popup>
                <div className="text-xs min-w-[140px]">
                  <div className="font-semibold">{s.name}</div>
                  <div className="text-ink-muted">{s.road} · km {s.km_marker}</div>
                  <div className="text-ink-muted">{zoneName(s.zone_id)}</div>
                  <div className="flex gap-2 mt-2">
                    <button onClick={() => openEdit(s)} className="text-brand underline text-xs">Edit</button>
                    <button onClick={() => setDelete(s)} className="text-sev-critical underline text-xs">Delete</button>
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}
          {pendingLatLng && <Marker position={pendingLatLng} icon={placingIcon()} />}
        </MapContainer>

        {placing && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 bg-orange text-white text-xs font-semibold px-4 py-2 rounded-full shadow-lg pointer-events-none">
            Click on the map to place the board
          </div>
        )}
      </div>

      {/* Edit/create modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl p-6 w-[400px] mx-4">
            <h3 className="font-semibold text-ink mb-4">{editing === 'new' ? 'Add Board' : 'Edit Board'}</h3>
            <div className="space-y-3 text-sm">
              <FormField label="Name"      value={form.name}      onChange={v => setForm(f => ({ ...f, name: v }))} placeholder="B43 LED Board 9" />
              <FormField label="Road"      value={form.road}      onChange={v => setForm(f => ({ ...f, road: v }))} placeholder="B43 Yala Road" />
              <FormField label="KM Marker" value={form.km_marker} onChange={v => setForm(f => ({ ...f, km_marker: v }))} placeholder="1.5" type="number" />
              <div>
                <label className="block text-xs text-ink-muted mb-1">Zone</label>
                <select className="w-full border border-line rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
                  value={form.zone_id} onChange={e => setForm(f => ({ ...f, zone_id: e.target.value }))}>
                  <option value="">Select zone…</option>
                  {zones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Latitude"  value={form.lat} onChange={v => setForm(f => ({ ...f, lat: v }))} placeholder="6.38200" type="number" />
                <FormField label="Longitude" value={form.lng} onChange={v => setForm(f => ({ ...f, lng: v }))} placeholder="81.48000" type="number" />
              </div>
              {pendingLatLng && editing === 'new' && <p className="text-xs text-sev-low">📍 Coordinates picked from map</p>}
              <div className="flex items-center gap-2">
                <input type="checkbox" id="online" checked={form.online} onChange={e => setForm(f => ({ ...f, online: e.target.checked }))} className="accent-brand" />
                <label htmlFor="online" className="text-sm text-ink">Board is online</label>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={cancelEdit} className="px-4 py-2 text-sm border border-line rounded hover:bg-surface-alt">Cancel</button>
              <button onClick={save} disabled={!form.name || !form.lat || !form.lng || !form.zone_id || busy}
                className="px-4 py-2 text-sm bg-brand text-white rounded hover:bg-brand-hover disabled:opacity-40">
                {busy ? 'Saving…' : 'Save Board'}
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete board"
        message={`Remove ${confirmDelete?.name} (${confirmDelete?.id})? This cannot be undone.`}
        confirmLabel="Delete" danger
        onConfirm={async () => { await remove(confirmDelete.id); setDelete(null) }}
        onCancel={() => setDelete(null)}
      />
    </div>
  )
}

function FormField({ label, value, onChange, placeholder, type = 'text' }) {
  return (
    <div>
      <label className="block text-xs text-ink-muted mb-1">{label}</label>
      <input type={type} step="any"
        className="w-full border border-line rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
        value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  )
}
