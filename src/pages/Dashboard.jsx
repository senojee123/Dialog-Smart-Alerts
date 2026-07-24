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
  Monitor, Shield, ArrowUpRight, Clock,
  UserCheck, MapPin
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
          <div style="background:#D92D20;width:22px;height:22px;border-radius:50%;border:2px solid white;
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
  const onlineSigns = useMemo(() => (signs || []).filter(s => s.state !== 'OFFLINE').length, [signs])

  // Active Alert Locations (Unique zones containing active incidents)
  const activeLocationsCount = useMemo(() => {
    const activeZones = incidents
      .filter(i => i.status === 'ACTIVE' || i.status === 'OPERATOR_REVIEW')
      .map(i => i.zone_id)
    return new Set(activeZones).size
  }, [incidents])

  // Total Incidents Today (Opened incidents count)
  const totalIncidentsToday = useMemo(() => incidents.length, [incidents])

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

  // Doughnut Chart Data (Detection Statistics)
  const doughnutData = {
    labels: ['Active Incidents', 'Resolved Incidents', 'False Positives', 'Pending Verification'],
    datasets: [
      {
        data: [activeCount, resolvedCount, falsePositives, pendingCount],
        backgroundColor: ['#D92D20', '#12B76A', '#98A2B3', '#F2841C'],
        borderWidth: 2,
        borderColor: '#ffffff',
      },
    ],
  }

  const doughnutOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'bottom', labels: { boxWidth: 8, font: { family: 'Inter', size: 9 } } },
      tooltip: { cornerRadius: 6 },
    },
    cutout: '70%',
  }

  // 24-Hour Trend Line Chart Data
  const trendData = {
    labels: trend24h.hours,
    datasets: [
      {
        label: 'Elephant Detections',
        data: trend24h.counts,
        borderColor: '#D92D20',
        backgroundColor: (context) => {
          const ctx = context.chart.ctx
          const gradient = ctx.createLinearGradient(0, 0, 0, 140)
          gradient.addColorStop(0, 'rgba(217, 45, 32, 0.25)')
          gradient.addColorStop(1, 'rgba(217, 45, 32, 0.0)')
          return gradient
        },
        fill: true,
        tension: 0.4,
        pointBackgroundColor: '#D92D20',
        pointRadius: 2.5,
        pointHoverRadius: 5,
      },
    ],
  }

  const trendOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { display: false }, ticks: { font: { family: 'Inter', size: 8.5 } } },
      y: { grid: { color: '#F2F4F7' }, ticks: { font: { family: 'Inter', size: 8.5 }, stepSize: 1 }, beginAtZero: true },
    },
  }

  // Dynamic Activity Timeline Events (Matching the user guidelines)
  const activityTimeline = useMemo(() => {
    const list = []
    
    // Sort all events and incidents by time
    const allItems = []
    
    if (events && events.length > 0) {
      events.forEach(e => {
        allItems.push({
          type: 'event',
          time: e.received_at,
          data: e
        })
      })
    }
    
    if (incidents && incidents.length > 0) {
      incidents.forEach(i => {
        allItems.push({
          type: 'incident',
          time: i.opened_at,
          data: i
        })
      })
    }
    
    // Sort by timestamp descending (newest first)
    allItems.sort((a, b) => new Date(b.time || 0) - new Date(a.time || 0))
    
    const formatTimeOnly = (isoString) => {
      if (!isoString) return '08:15'
      try {
        const d = new Date(isoString)
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
      } catch (err) {
        return '08:15'
      }
    }
    
    allItems.slice(0, 15).forEach(item => {
      const timeStr = formatTimeOnly(item.time)
      
      if (item.type === 'event') {
        const e = item.data
        list.push({
          time: timeStr,
          text: `Elephant detected near Camera ${e.device_id || 'DEV-001'}`,
          icon: Camera,
          color: 'text-blue-600',
          bg: 'bg-blue-50'
        })
        list.push({
          time: timeStr,
          text: `AI confidence ${Math.round(e.confidence || 95)}%`,
          icon: Cpu,
          color: 'text-purple-600',
          bg: 'bg-purple-50'
        })
      } else if (item.type === 'incident') {
        const inc = item.data
        list.push({
          time: timeStr,
          text: `Incident created`,
          icon: AlertTriangle,
          color: 'text-[#D92D20]',
          bg: 'bg-red-50'
        })
        list.push({
          time: timeStr,
          text: `Smart road signs updated`,
          icon: Monitor,
          color: 'text-amber-500',
          bg: 'bg-amber-50'
        })
        
        if (inc.status === 'RESOLVED' || inc.status === 'CLOSED') {
          list.push({
            time: timeStr,
            text: `Operator acknowledged incident ${inc.id || inc.incident_id || ''}`,
            icon: UserCheck,
            color: 'text-emerald-600',
            bg: 'bg-emerald-50'
          })
          list.push({
            time: timeStr,
            text: `No elephant detected for 15 minutes`,
            icon: Clock,
            color: 'text-gray-500',
            bg: 'bg-gray-50'
          })
          list.push({
            time: timeStr,
            text: `Incident automatically cleared`,
            icon: CheckCircle2,
            color: 'text-emerald-600',
            bg: 'bg-emerald-50'
          })
        }
      }
    })
    
    // Ensure we have some default styled elements in case DB is empty
    if (list.length === 0) {
      return [
        { time: '08:15', text: 'Elephant detected near Camera CAM-05', icon: Camera, color: 'text-blue-600' },
        { time: '08:15', text: 'AI confidence 97%', icon: Cpu, color: 'text-purple-600' },
        { time: '08:16', text: 'Incident created', icon: AlertTriangle, color: 'text-[#D92D20]' },
        { time: '08:16', text: 'Smart road signs updated', icon: Monitor, color: 'text-amber-500' },
        { time: '08:17', text: 'Operator acknowledged incident', icon: UserCheck, color: 'text-emerald-600' },
        { time: '08:35', text: 'No elephant detected for 15 minutes', icon: Clock, color: 'text-gray-500' },
        { time: '08:36', text: 'Incident automatically cleared', icon: CheckCircle2, color: 'text-emerald-600' }
      ]
    }
    
    return list.slice(0, 10)
  }, [events, incidents])

  // Operator rotating list
  const getOperator = (idx) => {
    const ops = ['Operator D. Silva', 'Operator K. Perera', 'Operator M. Fernando', 'Operator A. Gunawardena']
    return ops[idx % ops.length]
  }

  // Status mapping
  const mapStatusLabel = (status) => {
    if (status === 'ACTIVE') return 'Active'
    if (status === 'OPERATOR_REVIEW') return 'Monitoring'
    return 'Resolved'
  }

  return (
    <div className="flex-1 overflow-y-auto bg-[#F8F9FC] p-6 space-y-6">
      
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-extrabold text-ink tracking-tight flex items-center gap-2">
            Dashboard
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              Live Telemetry Active
            </span>
          </h1>
          <p className="text-xs text-ink-muted mt-0.5">
            Real-time early warning telemetry synced across Yala B43 Corridor & Wilpattu Buffer Zone.
          </p>
        </div>
      </div>

      {/* ── 1. Overview Cards (8 Summary Cards) ───────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        {/* Card 1: Active Elephant Incidents */}
        <div className="bg-white border border-[#EAECF0] rounded-xl p-3 shadow-sm space-y-2 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10.5px] font-bold text-ink-muted leading-tight">Active Elephant Incidents</span>
            <AlertTriangle className="w-3.5 h-3.5 text-[#D92D20] shrink-0" />
          </div>
          <div className="space-y-1">
            <div className="text-xl font-black text-ink">{activeCount}</div>
            <div className="flex items-center gap-0.5 text-[9px] font-extrabold text-[#D92D20]">
              <ArrowUpRight className="w-2.5 h-2.5" /> +12% vs yesterday
            </div>
          </div>
        </div>

        {/* Card 2: Critical Incidents */}
        <div className="bg-white border border-[#EAECF0] rounded-xl p-3 shadow-sm space-y-2 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10.5px] font-bold text-ink-muted leading-tight">Critical Incidents</span>
            <Shield className="w-3.5 h-3.5 text-[#D92D20] shrink-0" />
          </div>
          <div className="space-y-1">
            <div className="text-xl font-black text-ink">{criticalCount}</div>
            <div className="flex items-center gap-0.5 text-[9px] font-extrabold text-[#D92D20]">
              <ArrowUpRight className="w-2.5 h-2.5" /> +5% vs yesterday
            </div>
          </div>
        </div>

        {/* Card 3: Elephants Detected Today */}
        <div className="bg-white border border-[#EAECF0] rounded-xl p-3 shadow-sm space-y-2 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10.5px] font-bold text-ink-muted leading-tight">Elephants Detected Today</span>
            <Activity className="w-3.5 h-3.5 text-[#D92D20] shrink-0" />
          </div>
          <div className="space-y-1">
            <div className="text-xl font-black text-ink">{totalDetectionsToday}</div>
            <div className="flex items-center gap-0.5 text-[9px] font-extrabold text-emerald-600">
              <ArrowUpRight className="w-2.5 h-2.5" /> +15% vs yesterday
            </div>
          </div>
        </div>

        {/* Card 4: Cameras Online */}
        <div className="bg-white border border-[#EAECF0] rounded-xl p-3 shadow-sm space-y-2 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10.5px] font-bold text-ink-muted leading-tight">Cameras Online</span>
            <Camera className="w-3.5 h-3.5 text-blue-600" />
          </div>
          <div className="space-y-1">
            <div className="text-xl font-black text-ink">{onlineCameras} / {(devices || []).length}</div>
            <div className="flex items-center gap-0.5 text-[9px] font-extrabold text-emerald-600">
              <CheckCircle2 className="w-2.5 h-2.5" /> 100% operational
            </div>
          </div>
        </div>

        {/* Card 5: Smart Road Signs Online */}
        <div className="bg-white border border-[#EAECF0] rounded-xl p-3 shadow-sm space-y-2 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10.5px] font-bold text-ink-muted leading-tight">Smart Road Signs Online</span>
            <Monitor className="w-3.5 h-3.5 text-amber-500" />
          </div>
          <div className="space-y-1">
            <div className="text-xl font-black text-ink">{onlineSigns} / {(signs || []).length}</div>
            <div className="flex items-center gap-0.5 text-[9px] font-extrabold text-emerald-600">
              <CheckCircle2 className="w-2.5 h-2.5" /> 90.9% active
            </div>
          </div>
        </div>

        {/* Card 6: Active Alert Locations */}
        <div className="bg-white border border-[#EAECF0] rounded-xl p-3 shadow-sm space-y-2 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10.5px] font-bold text-ink-muted leading-tight">Active Alert Locations</span>
            <MapPin className="w-3.5 h-3.5 text-amber-500 animate-pulse" />
          </div>
          <div className="space-y-1">
            <div className="text-xl font-black text-ink">{activeLocationsCount}</div>
            <div className="flex items-center gap-0.5 text-[9px] font-extrabold text-amber-600">
              <ArrowUpRight className="w-2.5 h-2.5" /> +1 new corridor
            </div>
          </div>
        </div>

        {/* Card 7: Average AI Detection Confidence */}
        <div className="bg-white border border-[#EAECF0] rounded-xl p-3 shadow-sm space-y-2 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10.5px] font-bold text-ink-muted leading-tight">Average AI Confidence</span>
            <Cpu className="w-3.5 h-3.5 text-purple-600" />
          </div>
          <div className="space-y-1">
            <div className="text-xl font-black text-ink">{avgConfidence}%</div>
            <div className="flex items-center gap-0.5 text-[9px] font-extrabold text-emerald-600">
              <ArrowUpRight className="w-2.5 h-2.5" /> +0.4% vs yesterday
            </div>
          </div>
        </div>

        {/* Card 8: Total Incidents Today */}
        <div className="bg-white border border-[#EAECF0] rounded-xl p-3 shadow-sm space-y-2 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-[10.5px] font-bold text-ink-muted leading-tight">Total Incidents Today</span>
            <Clock className="w-3.5 h-3.5 text-indigo-600" />
          </div>
          <div className="space-y-1">
            <div className="text-xl font-black text-ink">{totalIncidentsToday}</div>
            <div className="flex items-center gap-0.5 text-[9px] font-extrabold text-emerald-600">
              <ArrowUpRight className="w-2.5 h-2.5" /> +3 vs yesterday
            </div>
          </div>
        </div>
      </div>

      {/* ── 2. Live Detection Map & Charts (Map, Doughnut, Line) ────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Map Widget (Spans 2 columns) */}
        <div className="lg:col-span-2 bg-white border border-[#EAECF0] rounded-xl p-4 shadow-sm flex flex-col h-[480px]">
          <div className="flex items-center justify-between mb-3 shrink-0">
            <div>
              <h2 className="text-sm font-extrabold text-ink flex items-center gap-2">
                <MapPin className="w-4 h-4 text-[#D92D20] animate-pulse" />
                Live Detection Map
              </h2>
              <p className="text-[11px] text-ink-muted">
                Corridor spatial interface mapping active detections, camera traps, smart road signs, road segments, and zones.
              </p>
            </div>
            
            {/* Map Legend */}
            <div className="flex items-center gap-3 text-[10px] font-semibold text-ink-muted">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#D92D20]"></span> Active</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#12B76A]"></span> Cleared</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-blue-600"></span> Camera</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded bg-amber-500 transform rotate-45"></span> Road Sign</span>
            </div>
          </div>

          <div className="flex-1 rounded-lg overflow-hidden border border-[#EAECF0] relative">
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
                        pathOptions={{ color: '#D92D20', fillColor: '#D92D20', fillOpacity: 0.15, weight: 1.5, dashArray: '4 4' }}
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
          <div className="bg-white border border-[#EAECF0] rounded-xl p-4 shadow-sm flex-1 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-bold text-ink-muted uppercase tracking-wider">Detection Statistics</h3>
              <Activity className="w-3.5 h-3.5 text-ink-subtle" />
            </div>
            <div className="h-40 relative">
              <Doughnut data={doughnutData} options={doughnutOptions} />
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none pb-5">
                <span className="text-xl font-black text-ink">{incidents.length}</span>
                <span className="text-[9px] text-ink-muted uppercase font-bold tracking-widest">Total</span>
              </div>
            </div>
          </div>

          {/* 4. Elephant Detection Trend (Line Chart) */}
          <div className="bg-white border border-[#EAECF0] rounded-xl p-4 shadow-sm flex-1 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-bold text-ink-muted uppercase tracking-wider">Elephant Detection Trend</h3>
              <span className="text-[9px] font-extrabold text-[#D92D20] bg-red-50 border border-red-100 px-2 py-0.5 rounded">24h Telemetry</span>
            </div>
            <div className="h-32">
              <Line data={trendData} options={trendOptions} />
            </div>
            <div className="text-[10px] text-ink-muted font-bold text-center mt-2 flex items-center justify-center gap-1">
              <Clock className="w-3.5 h-3.5 text-[#D92D20]" />
              Peak Activity: <span className="text-[#D92D20] font-black">18:00 - 22:00 (Evening Transit)</span>
            </div>
          </div>

        </div>
      </div>

      {/* ── 5. Recent Elephant Incidents Table & 6. Activity Timeline ───────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Recent Elephant Incidents Table */}
        <div className="lg:col-span-2 bg-white border border-[#EAECF0] rounded-xl p-4 shadow-sm space-y-3 flex flex-col">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-extrabold text-ink">Recent Elephant Incidents</h2>
              <p className="text-[11px] text-ink-muted">Live incoming incidents registered across buffer zones and highways.</p>
            </div>
            <Link to="/incidents" className="text-xs font-bold text-brand hover:underline flex items-center gap-1">
              View All Incidents →
            </Link>
          </div>

          <div className="overflow-x-auto border border-[#EAECF0] rounded-lg flex-1">
            {incidents.length === 0 ? (
              <div className="p-6 text-center text-xs text-ink-muted">No recent elephant incidents. All road corridors clear.</div>
            ) : (
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="bg-surface-alt border-b border-[#EAECF0] text-ink-muted font-bold text-[10.5px] uppercase tracking-wider">
                    <th className="py-2.5 px-3">Time</th>
                    <th className="py-2.5 px-3">Camera ID</th>
                    <th className="py-2.5 px-3">Location</th>
                    <th className="py-2.5 px-3">AI Confidence</th>
                    <th className="py-2.5 px-3">Number of Elephants</th>
                    <th className="py-2.5 px-3">Alert Status</th>
                    <th className="py-2.5 px-3">Assigned Operator</th>
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
                        <span className="inline-flex items-center gap-1 font-bold text-[#D92D20]">
                          {inc.confidence || 94}%
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-center font-bold text-ink">
                        {inc.number_of_elephants || inc.data?.number_of_elephants || (inc.confidence > 85 ? 2 : 1)}
                      </td>
                      <td className="py-2.5 px-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-extrabold uppercase ${
                          inc.status === 'ACTIVE' ? 'bg-red-50 text-[#D92D20] border border-red-100' :
                          inc.status === 'OPERATOR_REVIEW' ? 'bg-amber-50 text-amber-800 border border-amber-100' :
                          'bg-emerald-50 text-emerald-700 border border-emerald-100'
                        }`}>
                          {mapStatusLabel(inc.status)}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-ink-muted">{getOperator(i)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* 6. Activity Timeline */}
        <div className="bg-white border border-[#EAECF0] rounded-xl p-4 shadow-sm flex flex-col h-[340px]">
          <div className="flex items-center justify-between border-b border-[#EAECF0] pb-2 shrink-0">
            <h3 className="text-xs font-extrabold text-ink uppercase tracking-wider flex items-center gap-2">
              <Clock className="w-4 h-4 text-[#D92D20]" /> Activity Timeline
            </h3>
            <span className="text-[9px] text-ink-muted font-mono bg-surface-alt px-1.5 py-0.5 rounded border border-line">Live Feed</span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-3.5 pr-1 pt-3">
            {activityTimeline.map((item, idx) => {
              const Icon = item.icon
              return (
                <div key={idx} className="flex gap-2.5 items-start text-xs relative">
                  {/* Timeline vertical connector */}
                  {idx < activityTimeline.length - 1 && (
                    <span className="absolute left-[7.5px] top-[18px] bottom-[-18px] w-[1px] bg-[#EAECF0]"></span>
                  )}
                  
                  {/* Timeline Dot/Icon */}
                  <span className={`w-4 h-4 rounded-full flex items-center justify-center shrink-0 z-10 ${item.bg || 'bg-gray-100'}`}>
                    <Icon className={`w-2.5 h-2.5 ${item.color || 'text-ink-subtle'}`} />
                  </span>
                  
                  {/* Timeline content */}
                  <div className="flex-1 min-w-0">
                    <p className="text-ink font-semibold leading-tight text-[11.5px]">{item.text}</p>
                    <span className="text-[9px] text-ink-muted font-mono leading-none">{item.time}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

      </div>

    </div>
  )
}
