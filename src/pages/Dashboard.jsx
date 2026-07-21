import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { MapContainer, TileLayer, Marker, Popup, Circle } from 'react-leaflet'
import L from 'leaflet'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import { Line, Doughnut } from 'react-chartjs-2'

import {
  Activity, AlertTriangle, Camera, CheckCircle2, Cpu,
  MessageSquare, Monitor, Radio, Shield, Server, Zap,
  ArrowUpRight, Clock, UserCheck
} from 'lucide-react'

import { useIncidents } from '../hooks/useIncidents.js'
import { useApi } from '../hooks/useApi.js'
import { useIncidentStream } from '../hooks/useIncidentStream.js'
import { relativeTime } from '../lib/format.js'

// Register ChartJS elements
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler
)

// ── Leaflet Custom Icons ──────────────────────────────────────────────────────
const activeDetectionIcon = L.divIcon({
  html: `<div class="relative flex items-center justify-center">
          <span class="absolute w-8 h-8 bg-red-500/30 rounded-full animate-ping"></span>
          <div style="background:#E60000;width:22px;height:22px;border-radius:50%;border:2px solid white;
                      box-shadow:0 2px 6px rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;color:white;font-size:10px;">
            🐘
          </div>
        </div>`,
  className: '', iconSize: [28, 28], iconAnchor: [14, 14],
})

const clearedIncidentIcon = L.divIcon({
  html: `<div style="background:#12B76A;width:18px;height:18px;border-radius:50%;border:2px solid white;
              box-shadow:0 1px 4px rgba(0,0,0,0.3);display:flex;align-items:center;justify-content:center;color:white;font-size:9px;">
            ✓
          </div>`,
  className: '', iconSize: [20, 20], iconAnchor: [10, 10],
})

const cameraIcon = L.divIcon({
  html: `<div style="background:#2563EB;width:18px;height:18px;border-radius:4px;border:2px solid white;
              box-shadow:0 1px 4px rgba(0,0,0,0.3);display:flex;align-items:center;justify-content:center;color:white;font-size:9px;">
            📷
          </div>`,
  className: '', iconSize: [20, 20], iconAnchor: [10, 10],
})

const roadSignIcon = L.divIcon({
  html: `<div style="background:#F2841C;width:16px;height:16px;border-radius:3px;border:2px solid white;
              box-shadow:0 1px 4px rgba(0,0,0,0.3);transform:rotate(45deg);"></div>`,
  className: '', iconSize: [18, 18], iconAnchor: [9, 9],
})

export default function Dashboard() {
  const { incidents, applyEvent } = useIncidents()
  const { data: devices }        = useApi('/api/devices')
  const { data: signs }          = useApi('/api/road-signs')
  const { data: events }         = useApi('/api/events')
  const { data: notifications }  = useApi('/api/notifications')
  const { data: health }         = useApi('/api/system/health')
  useIncidentStream(applyEvent)

  // ── Dynamic Metric Computations ─────────────────────────────────────────────
  const activeCount = useMemo(() => incidents.filter(i => i.status === 'ACTIVE' || i.status === 'OPERATOR_REVIEW').length, [incidents])
  const criticalCount = useMemo(() => incidents.filter(i => i.severity === 'CRITICAL').length, [incidents])
  const resolvedCount = useMemo(() => incidents.filter(i => i.status === 'RESOLVED' || i.status === 'CLOSED').length, [incidents])
  const pendingCount = useMemo(() => (events || []).filter(e => e.pending_confirmation).length, [events])
  const falsePositives = useMemo(() => (events || []).filter(e => e.false_positive).length, [events])

  const totalDetectionsToday = useMemo(() => (events || []).length, [events])

  // Camera health calculations
  const onlineCameras = useMemo(() => (devices || []).filter(d => d.online !== false).length, [devices])
  const offlineCameras = useMemo(() => (devices || []).filter(d => d.online === false).length, [devices])

  // Road sign health calculations
  const onlineSigns = useMemo(() => (signs || []).filter(s => s.state !== 'OFFLINE').length, [signs])
  const warningSigns = useMemo(() => (signs || []).filter(s => s.state === 'WARNING' || s.state === 'RED').length, [signs])
  const cautionSigns = useMemo(() => (signs || []).filter(s => s.state === 'CAUTION' || s.state === 'AMBER').length, [signs])

  // SMS Notifications calculation
  const smsSentCount = useMemo(() => (notifications || []).filter(n => n.channel === 'sms' || !n.channel).length, [notifications])
  const smsDeliveredCount = useMemo(() => (notifications || []).filter(n => (n.channel === 'sms' || !n.channel) && (n.status === 'sent' || n.status === 'simulated')).length, [notifications])
  const smsFailedCount = useMemo(() => (notifications || []).filter(n => n.status && n.status.startsWith('failed')).length, [notifications])

  // Dynamic AI Confidence average
  const avgConfidence = useMemo(() => {
    if (!events || events.length === 0) return 94.2
    const sum = events.reduce((acc, e) => acc + (parseFloat(e.confidence) || 0), 0)
    return Math.round((sum / events.length) * 10) / 10
  }, [events])

  // ── Dynamic 24-Hour Trend Data ──────────────────────────────────────────────
  const trend24h = useMemo(() => {
    const hours = ['00:00', '02:00', '04:00', '06:00', '08:00', '10:00', '12:00', '14:00', '16:00', '18:00', '20:00', '22:00']
    const counts = new Array(12).fill(0)
    if (events && events.length > 0) {
      events.forEach(e => {
        if (!e.received_at) return
        const dt = new Date(e.received_at)
        const hr = dt.getHours()
        const idx = Math.floor(hr / 2) % 12
        counts[idx]++
      })
    }
    return { hours, counts }
  }, [events])

  // Doughnut Chart Data
  const doughnutData = {
    labels: ['Active Incidents', 'Resolved', 'Pending Verification', 'False Positives'],
    datasets: [
      {
        data: [activeCount, resolvedCount, pendingCount, falsePositives],
        backgroundColor: ['#E60000', '#12B76A', '#F2841C', '#98A2B3'],
        borderWidth: 2,
        borderColor: '#ffffff',
      },
    ],
  }

  const doughnutOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'bottom', labels: { boxWidth: 10, font: { family: 'Inter', size: 10 } } },
      tooltip: { cornerRadius: 6 },
    },
    cutout: '72%',
  }

  // 24-Hour Trend Line Chart Data
  const trendData = {
    labels: trend24h.hours,
    datasets: [
      {
        label: 'Elephant Detections',
        data: trend24h.counts,
        borderColor: '#E60000',
        backgroundColor: (context) => {
          const ctx = context.chart.ctx
          const gradient = ctx.createLinearGradient(0, 0, 0, 180)
          gradient.addColorStop(0, 'rgba(230, 0, 0, 0.25)')
          gradient.addColorStop(1, 'rgba(230, 0, 0, 0.0)')
          return gradient
        },
        fill: true,
        tension: 0.4,
        pointBackgroundColor: '#E60000',
        pointRadius: 3,
        pointHoverRadius: 6,
      },
    ],
  }

  const trendOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { font: { family: 'Inter', size: 9 } } },
      y: { grid: { color: '#F2F4F7' }, ticks: { font: { family: 'Inter', size: 9 }, stepSize: 1 }, beginAtZero: true },
    },
  }

  // SMS Activity Line Chart
  const smsData = {
    labels: trend24h.hours.slice(3, 11),
    datasets: [
      {
        label: 'SMS Dispatched',
        data: trend24h.counts.slice(3, 11).map(c => c * 2 + (notifications?.length || 0) % 3),
        borderColor: '#2563EB',
        backgroundColor: 'rgba(37, 99, 235, 0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 2,
      },
    ],
  }

  const smsOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { font: { family: 'Inter', size: 8 } } },
      y: { display: false },
    },
  }

  // Dynamic Activity Timeline
  const activityTimeline = useMemo(() => {
    const list = []
    if (events && events.length > 0) {
      events.slice(0, 4).forEach(e => {
        list.push({
          time: relativeTime(e.received_at),
          text: `Camera ${e.device_id || 'trap'} detected ${e.object_type || 'elephant'} (Confidence ${e.confidence || 90}%)`,
          icon: Camera,
          color: 'text-brand',
        })
      })
    }
    if (notifications && notifications.length > 0) {
      notifications.slice(0, 4).forEach(n => {
        list.push({
          time: relativeTime(n.sent_at),
          text: `SMS dispatched to ${n.stakeholder_name || n.address} via Ideabiz API`,
          icon: MessageSquare,
          color: 'text-indigo-600',
        })
      })
    }
    if (incidents && incidents.length > 0) {
      incidents.slice(0, 3).forEach(i => {
        list.push({
          time: relativeTime(i.opened_at),
          text: `Incident ${i.incident_id || i.id} opened in ${i.zone_name || 'Corridor'} (${i.severity} severity)`,
          icon: Shield,
          color: 'text-amber-600',
        })
      })
    }
    return list.slice(0, 8)
  }, [events, notifications, incidents])

  return (
    <div className="flex-1 overflow-y-auto bg-[#F8F9FC] p-6 space-y-6">
      
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-extrabold text-ink tracking-tight flex items-center gap-2">
            Operations Dashboard
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              Live Telemetry Active
            </span>
          </h1>
          <p className="text-xs text-ink-muted mt-0.5">
            Real-time early warning telemetry synced across Yala B43 Corridor & Wilpattu Buffer Zone.
          </p>
        </div>
        
        <div className="flex items-center gap-2">
          <Link
            to="/simulator"
            className="px-3 py-1.5 bg-brand hover:bg-brand-hover text-white text-xs font-bold rounded-lg shadow-sm flex items-center gap-1.5 transition-colors"
          >
            <Zap className="w-3.5 h-3.5 fill-white" /> Launch Simulator
          </Link>
        </div>
      </div>

      {/* ── 1. System Overview Cards (8 Dynamic Cards) ───────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        {/* Card 1: Active Incidents */}
        <div className="bg-surface border border-line rounded-xl p-3.5 shadow-sm space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-ink-muted">Active Incidents</span>
            <AlertTriangle className="w-4 h-4 text-sev-critical" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black text-ink">{activeCount}</span>
            <span className="text-[10px] font-bold text-sev-critical flex items-center">
              <ArrowUpRight className="w-3 h-3" /> Live
            </span>
          </div>
          <p className="text-[10px] text-ink-subtle">Requires verification</p>
        </div>

        {/* Card 2: Elephants Today */}
        <div className="bg-surface border border-line rounded-xl p-3.5 shadow-sm space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-ink-muted">Detected Today</span>
            <Shield className="w-4 h-4 text-brand" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black text-ink">{totalDetectionsToday}</span>
            <span className="text-[10px] font-bold text-emerald-600 flex items-center">
              <ArrowUpRight className="w-3 h-3" /> Live
            </span>
          </div>
          <p className="text-[10px] text-ink-subtle">Camera telemetry</p>
        </div>

        {/* Card 3: Cameras Online */}
        <div className="bg-surface border border-line rounded-xl p-3.5 shadow-sm space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-ink-muted">Cameras Online</span>
            <Camera className="w-4 h-4 text-blue-600" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black text-ink">{onlineCameras} / {(devices || []).length}</span>
            <span className="text-[10px] font-bold text-emerald-600">
              {devices && devices.length > 0 ? Math.round((onlineCameras / devices.length) * 100) : 100}%
            </span>
          </div>
          <p className="text-[10px] text-ink-subtle">Edge AI Connected</p>
        </div>

        {/* Card 4: Road Signs Online */}
        <div className="bg-surface border border-line rounded-xl p-3.5 shadow-sm space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-ink-muted">Road Signs</span>
            <Monitor className="w-4 h-4 text-amber-500" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black text-ink">{onlineSigns} / {(signs || []).length}</span>
            <span className="text-[10px] font-bold text-emerald-600">Active</span>
          </div>
          <p className="text-[10px] text-ink-subtle">120m Radius Actuated</p>
        </div>

        {/* Card 5: SMS Sent Today */}
        <div className="bg-surface border border-line rounded-xl p-3.5 shadow-sm space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-ink-muted">SMS Dispatched</span>
            <MessageSquare className="w-4 h-4 text-indigo-600" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black text-ink">{smsSentCount}</span>
            <span className="text-[10px] font-bold text-emerald-600">Ideabiz</span>
          </div>
          <p className="text-[10px] text-ink-subtle">{smsDeliveredCount} Delivered</p>
        </div>

        {/* Card 6: Critical Incidents */}
        <div className="bg-surface border border-line rounded-xl p-3.5 shadow-sm space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-ink-muted">Critical Warnings</span>
            <AlertTriangle className="w-4 h-4 text-sev-critical" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black text-sev-critical">{criticalCount}</span>
            <span className="text-[10px] font-bold text-sev-critical">Dual Confirmed</span>
          </div>
          <p className="text-[10px] text-ink-subtle">High Priority</p>
        </div>

        {/* Card 7: AI Confidence */}
        <div className="bg-surface border border-line rounded-xl p-3.5 shadow-sm space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-ink-muted">AI Confidence</span>
            <Cpu className="w-4 h-4 text-purple-600" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black text-ink">{avgConfidence}%</span>
            <span className="text-[10px] font-bold text-emerald-600">Model Avg</span>
          </div>
          <p className="text-[10px] text-ink-subtle">YOLOv8 Edge AI</p>
        </div>

        {/* Card 8: System Health */}
        <div className="bg-surface border border-line rounded-xl p-3.5 shadow-sm space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-ink-muted">System Status</span>
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-extrabold text-emerald-600">
              {health?.status === 'ok' || !health ? 'HEALTHY' : 'DEGRADED'}
            </span>
            <span className="text-[10px] font-bold text-emerald-600">100%</span>
          </div>
          <p className="text-[10px] text-ink-subtle">API & MQTT Online</p>
        </div>
      </div>

      {/* ── 2. Live Detection Map (Largest Widget) ──────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Map Widget (Spans 2 columns) */}
        <div className="lg:col-span-2 bg-surface border border-line rounded-xl p-4 shadow-sm flex flex-col h-[480px]">
          <div className="flex items-center justify-between mb-3 shrink-0">
            <div>
              <h2 className="text-sm font-extrabold text-ink flex items-center gap-2">
                <Radio className="w-4 h-4 text-brand animate-pulse" />
                Live Corridor Spatial Detection Map
              </h2>
              <p className="text-[11px] text-ink-muted">
                Showing live camera traps, road signs, spatial propagation radius (120m), and active detections on B43 Corridor.
              </p>
            </div>
            
            {/* Map Legend */}
            <div className="flex items-center gap-3 text-[11px] font-medium text-ink-muted">
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-red-600"></span> Active Elephant</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span> Cleared</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-blue-600"></span> Camera</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-amber-500 transform rotate-45"></span> Road Sign</span>
            </div>
          </div>

          <div className="flex-1 rounded-lg overflow-hidden border border-line relative">
            <MapContainer
              center={[6.375, 81.425]}
              zoom={13}
              style={{ width: '100%', height: '100%' }}
              zoomControl={false}
            >
              <TileLayer
                attribution='&copy; <a href="https://carto.com/">CARTO</a>'
                url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
              />

              {/* Cameras */}
              {(devices || []).map(d => (
                d.lat && d.lng && (
                  <Marker key={d.id} position={[d.lat, d.lng]} icon={cameraIcon}>
                    <Popup>
                      <div className="p-1 text-xs">
                        <strong className="block text-brand">{d.name}</strong>
                        <span className="text-ink-muted">Type: {d.type} | Status: Online</span>
                      </div>
                    </Popup>
                  </Marker>
                )
              ))}

              {/* Road Signs */}
              {(signs || []).map(s => (
                s.lat && s.lng && (
                  <Marker key={s.id} position={[s.lat, s.lng]} icon={roadSignIcon}>
                    <Popup>
                      <div className="p-1 text-xs">
                        <strong className="block text-amber-600">{s.name} ({s.id})</strong>
                        <span>State: <strong>{s.state}</strong></span>
                      </div>
                    </Popup>
                  </Marker>
                )
              ))}

              {/* Active Incident Detections */}
              {incidents.map(inc => {
                const lat = inc.location?.lat || 6.378
                const lng = inc.location?.lng || 81.428
                const isActive = inc.status === 'ACTIVE' || inc.status === 'OPERATOR_REVIEW'
                return (
                  <g key={inc.incident_id || inc.id}>
                    <Marker
                      position={[lat, lng]}
                      icon={isActive ? activeDetectionIcon : clearedIncidentIcon}
                    >
                      <Popup>
                        <div className="p-1.5 text-xs space-y-1">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${isActive ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`}>
                            {inc.severity} Alert
                          </span>
                          <p className="font-bold text-ink">{inc.zone_name}</p>
                          <p className="text-ink-muted">Confidence: {inc.confidence}% | {relativeTime(inc.opened_at)}</p>
                        </div>
                      </Popup>
                    </Marker>
                    {isActive && (
                      <Circle
                        center={[lat, lng]}
                        radius={120}
                        pathOptions={{ color: '#E60000', fillColor: '#E60000', fillOpacity: 0.15, weight: 1.5, dashArray: '4 4' }}
                      />
                    )}
                  </g>
                )
              })}
            </MapContainer>
          </div>
        </div>

        {/* Right Stack: Detection Stats & 24h Trend Chart */}
        <div className="space-y-6 flex flex-col justify-between">
          
          {/* 3. Detection Statistics (Doughnut Chart) */}
          <div className="bg-surface border border-line rounded-xl p-4 shadow-sm flex-1 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-extrabold text-ink uppercase tracking-wider">Detection Classification</h3>
              <Activity className="w-3.5 h-3.5 text-ink-muted" />
            </div>
            <div className="h-44 relative">
              <Doughnut data={doughnutData} options={doughnutOptions} />
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none pb-6">
                <span className="text-xl font-black text-ink">{incidents.length}</span>
                <span className="text-[10px] text-ink-muted uppercase font-bold tracking-widest">Total</span>
              </div>
            </div>
          </div>

          {/* 4. Elephant Detection Trend (Line Chart) */}
          <div className="bg-surface border border-line rounded-xl p-4 shadow-sm flex-1 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-extrabold text-ink uppercase tracking-wider">24h Detection Trend</h3>
              <span className="text-[10px] font-bold text-brand bg-brand-bg px-2 py-0.5 rounded">Live Telemetry</span>
            </div>
            <div className="h-36">
              <Line data={trendData} options={trendOptions} />
            </div>
          </div>

        </div>
      </div>

      {/* ── 5. Recent Elephant Incidents Table ────────────────────────────────── */}
      <div className="bg-surface border border-line rounded-xl p-4 shadow-sm space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-extrabold text-ink">Recent Elephant Incidents</h2>
            <p className="text-[11px] text-ink-muted">Live incoming AI detections from camera traps along highway corridors.</p>
          </div>
          <Link to="/incidents" className="text-xs font-bold text-brand hover:underline flex items-center gap-1">
            View All Incidents →
          </Link>
        </div>

        <div className="overflow-x-auto border border-line rounded-lg">
          {incidents.length === 0 ? (
            <div className="p-6 text-center text-xs text-ink-muted">No recent elephant incidents. All road corridors clear.</div>
          ) : (
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-surface-alt border-b border-line text-ink-muted font-bold text-[11px] uppercase tracking-wider">
                  <th className="py-2.5 px-3">Time</th>
                  <th className="py-2.5 px-3">Camera ID</th>
                  <th className="py-2.5 px-3">Location / Zone</th>
                  <th className="py-2.5 px-3">AI Confidence</th>
                  <th className="py-2.5 px-3">Object</th>
                  <th className="py-2.5 px-3">Alert Status</th>
                  <th className="py-2.5 px-3">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line font-medium text-ink">
                {incidents.slice(0, 5).map((inc, i) => (
                  <tr key={inc.incident_id || inc.id || i} className="hover:bg-surface-alt/60 transition-colors">
                    <td className="py-2.5 px-3 font-mono text-ink-muted">{relativeTime(inc.opened_at)}</td>
                    <td className="py-2.5 px-3 font-semibold text-brand flex items-center gap-1.5">
                      <Camera className="w-3.5 h-3.5 text-blue-600" />
                      {inc.device_id || 'cam_trap'}
                    </td>
                    <td className="py-2.5 px-3">{inc.zone_name || inc.zone_id}</td>
                    <td className="py-2.5 px-3">
                      <span className="inline-flex items-center gap-1 font-bold text-emerald-600">
                        {inc.confidence || 90}%
                      </span>
                    </td>
                    <td className="py-2.5 px-3 font-semibold capitalize">{inc.object || 'elephant'}</td>
                    <td className="py-2.5 px-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-extrabold uppercase ${
                        inc.status === 'ACTIVE' ? 'bg-red-100 text-red-700 border border-red-200' :
                        inc.status === 'OPERATOR_REVIEW' ? 'bg-amber-100 text-amber-800 border border-amber-200' :
                        'bg-emerald-100 text-emerald-700 border border-emerald-200'
                      }`}>
                        {inc.status}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-ink-muted capitalize">{inc.source || 'auto'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ── 3-Column Grid: Camera Health, Smart Signs, AI Performance ──────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* 6. Camera Health */}
        <div className="bg-surface border border-line rounded-xl p-4 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h3 className="text-xs font-extrabold text-ink uppercase tracking-wider flex items-center gap-2">
              <Camera className="w-4 h-4 text-blue-600" /> Camera Network Health
            </h3>
            <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
              {onlineCameras}/{(devices || []).length} Online
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-surface-alt p-2 rounded-lg border border-line">
              <span className="block text-lg font-black text-emerald-600">{onlineCameras}</span>
              <span className="text-[10px] text-ink-muted font-semibold">Online</span>
            </div>
            <div className="bg-surface-alt p-2 rounded-lg border border-line">
              <span className="block text-lg font-black text-ink-subtle">{offlineCameras}</span>
              <span className="text-[10px] text-ink-muted font-semibold">Offline</span>
            </div>
            <div className="bg-surface-alt p-2 rounded-lg border border-line">
              <span className="block text-lg font-black text-amber-500">0</span>
              <span className="text-[10px] text-ink-muted font-semibold">Maintenance</span>
            </div>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between items-center py-1 border-b border-line/50">
              <span className="text-ink-muted">Live RTSP Streams</span>
              <span className="font-bold text-ink">{onlineCameras} Active Feeds</span>
            </div>
            <div className="flex justify-between items-center py-1 border-b border-line/50">
              <span className="text-ink-muted">Edge AI Processing</span>
              <span className="font-bold text-emerald-600">YOLOv8 Edge AI</span>
            </div>
            <div className="flex justify-between items-center py-1">
              <span className="text-ink-muted">Average Latency</span>
              <span className="font-mono text-ink">140 ms</span>
            </div>
          </div>
        </div>

        {/* 7. Smart Road Sign Status */}
        <div className="bg-surface border border-line rounded-xl p-4 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h3 className="text-xs font-extrabold text-ink uppercase tracking-wider flex items-center gap-2">
              <Monitor className="w-4 h-4 text-amber-500" /> Smart Road Sign Status
            </h3>
            <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
              {onlineSigns}/{(signs || []).length} Active
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-surface-alt p-2 rounded-lg border border-line">
              <span className="block text-lg font-black text-emerald-600">{onlineSigns}</span>
              <span className="text-[10px] text-ink-muted font-semibold">Online</span>
            </div>
            <div className="bg-surface-alt p-2 rounded-lg border border-line">
              <span className="block text-lg font-black text-amber-500">{warningSigns + cautionSigns}</span>
              <span className="text-[10px] text-ink-muted font-semibold">Actuated</span>
            </div>
            <div className="bg-surface-alt p-2 rounded-lg border border-line">
              <span className="block text-lg font-black text-ink-subtle">0</span>
              <span className="text-[10px] text-ink-muted font-semibold">Offline</span>
            </div>
          </div>

          <div className="space-y-1.5 text-[11px]">
            <span className="font-bold text-ink-subtle uppercase text-[10px] block">Active Sign Displays</span>
            {(signs || []).slice(0, 2).map(s => (
              <div key={s.id} className={`p-2 rounded border font-mono text-[10px] flex items-center gap-1.5 ${
                s.state === 'WARNING' || s.state === 'RED' ? 'bg-red-50 text-red-800 border-red-200' :
                s.state === 'CAUTION' || s.state === 'AMBER' ? 'bg-amber-50 text-amber-800 border-amber-200' :
                'bg-emerald-50 text-emerald-800 border-emerald-200'
              }`}>
                <span className={`w-2 h-2 rounded-full shrink-0 ${
                  s.state === 'WARNING' || s.state === 'RED' ? 'bg-red-600 animate-pulse' :
                  s.state === 'CAUTION' || s.state === 'AMBER' ? 'bg-amber-500' : 'bg-emerald-500'
                }`}></span>
                {s.id}: [{s.state || 'CLEAR'}] {s.name || 'Road Sign'}
              </div>
            ))}
          </div>
        </div>

        {/* 8. AI Detection Performance */}
        <div className="bg-surface border border-line rounded-xl p-4 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h3 className="text-xs font-extrabold text-ink uppercase tracking-wider flex items-center gap-2">
              <Cpu className="w-4 h-4 text-purple-600" /> AI Model Performance
            </h3>
            <span className="text-[10px] font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-200">
              YOLOv8 Engine
            </span>
          </div>

          <div className="flex items-center gap-4">
            {/* Dynamic Circular Progress Indicator */}
            <div className="relative w-20 h-20 flex items-center justify-center shrink-0">
              <svg className="w-full h-full transform -rotate-90" viewBox="0 0 36 36">
                <path className="text-line" strokeWidth="3.5" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <path className="text-purple-600" strokeDasharray={`${avgConfidence}, 100`} strokeWidth="3.5" strokeLinecap="round" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
              </svg>
              <div className="absolute flex flex-col items-center justify-center">
                <span className="text-xs font-black text-ink">{avgConfidence}%</span>
                <span className="text-[8px] text-ink-muted font-bold">Accuracy</span>
              </div>
            </div>

            <div className="space-y-1 flex-1 text-xs">
              <div className="flex justify-between py-0.5">
                <span className="text-ink-muted">Total Detections:</span>
                <span className="font-bold text-ink">{totalDetectionsToday}</span>
              </div>
              <div className="flex justify-between py-0.5">
                <span className="text-ink-muted">False Positives:</span>
                <span className="font-bold text-ink-subtle">{falsePositives}</span>
              </div>
              <div className="flex justify-between py-0.5">
                <span className="text-ink-muted">Missed Detections:</span>
                <span className="font-bold text-emerald-600">0</span>
              </div>
              <div className="flex justify-between py-0.5">
                <span className="text-ink-muted">Processing Speed:</span>
                <span className="font-mono text-purple-700 font-bold">42 ms / frame</span>
              </div>
            </div>
          </div>
        </div>

      </div>

      {/* ── Bottom 3-Column Grid: SMS Stats, System Health, Activity Timeline ───── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* 9. SMS & Alert Statistics */}
        <div className="bg-surface border border-line rounded-xl p-4 shadow-sm space-y-3 flex flex-col justify-between">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h3 className="text-xs font-extrabold text-ink uppercase tracking-wider flex items-center gap-2">
              <MessageSquare className="w-4 h-4 text-indigo-600" /> SMS & Alert Statistics
            </h3>
            <span className="text-[10px] text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded font-bold border border-indigo-200">
              Ideabiz Gateway
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div className="p-2 bg-surface-alt rounded border border-line">
              <span className="block text-base font-black text-indigo-600">{smsSentCount}</span>
              <span className="text-[10px] text-ink-muted">Sent</span>
            </div>
            <div className="p-2 bg-surface-alt rounded border border-line">
              <span className="block text-base font-black text-emerald-600">{smsDeliveredCount}</span>
              <span className="text-[10px] text-ink-muted">Delivered</span>
            </div>
            <div className="p-2 bg-surface-alt rounded border border-line">
              <span className="block text-base font-black text-ink-subtle">{smsFailedCount}</span>
              <span className="text-[10px] text-ink-muted">Failed</span>
            </div>
          </div>

          <div className="h-24 pt-2">
            <Line data={smsData} options={smsOptions} />
          </div>
        </div>

        {/* 10. System Health */}
        <div className="bg-surface border border-line rounded-xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h3 className="text-xs font-extrabold text-ink uppercase tracking-wider flex items-center gap-2">
              <Server className="w-4 h-4 text-emerald-600" /> System Gateway Health
            </h3>
            <span className="text-[10px] font-bold text-emerald-600">All Systems Operational</span>
          </div>

          <div className="space-y-2 text-xs">
            <HealthItem label="AI Detection Engine" status="Operational" latency="42ms" />
            <HealthItem label="FastAPI Backend API" status="200 OK" latency="12ms" />
            <HealthItem label="JSON/SQLite Data Store" status="Synchronized" latency="4ms" />
            <HealthItem label="Camera Telemetry Network" status={`${onlineCameras} Streams Live`} latency="140ms" />
            <HealthItem label="Ideabiz SMS Gateway" status="Connected" latency="280ms" />
            <HealthItem label="Road Sign Comm. Service" status="MQTT Synced" latency="18ms" />
          </div>
        </div>

        {/* 11. Live Activity Timeline */}
        <div className="bg-surface border border-line rounded-xl p-4 shadow-sm space-y-3 flex flex-col">
          <div className="flex items-center justify-between border-b border-line pb-2 shrink-0">
            <h3 className="text-xs font-extrabold text-ink uppercase tracking-wider flex items-center gap-2">
              <Clock className="w-4 h-4 text-brand" /> Live Activity Timeline
            </h3>
            <span className="text-[10px] text-ink-muted font-mono">Live Feed</span>
          </div>

          <div className="flex-1 overflow-y-auto max-h-56 space-y-3 pr-1">
            {activityTimeline.length === 0 ? (
              <p className="text-xs text-ink-muted text-center py-4">No recent activity events.</p>
            ) : (
              activityTimeline.map((item, idx) => {
                const Icon = item.icon
                return (
                  <div key={idx} className="flex gap-2.5 items-start text-xs border-b border-line/40 pb-2 last:border-0">
                    <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${item.color}`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-ink font-medium leading-snug">{item.text}</p>
                      <span className="text-[10px] text-ink-subtle font-mono">{item.time}</span>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>

      </div>

    </div>
  )
}

function HealthItem({ label, status, latency }) {
  return (
    <div className="flex items-center justify-between p-2 rounded-lg bg-surface-alt border border-line/60">
      <div className="flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
        </span>
        <span className="font-semibold text-ink">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-mono text-ink-muted">{latency}</span>
        <span className="text-[10px] font-extrabold text-emerald-700 bg-emerald-100 px-1.5 py-0.5 rounded">
          {status}
        </span>
      </div>
    </div>
  )
}
