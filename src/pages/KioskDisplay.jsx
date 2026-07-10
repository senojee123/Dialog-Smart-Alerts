import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { ShieldCheck, AlertTriangle, Clock, Radio, Activity } from 'lucide-react'

export default function KioskDisplay() {
  const { deviceId } = useParams()
  const [state, setState] = useState({ status: 'CLEAR', incident: null })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [currentTime, setCurrentTime] = useState(new Date())

  // Keep ticking local clock
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  // Function to fetch active status
  const fetchStatus = async () => {
    try {
      const res = await fetch(`/api/kiosks/${deviceId}/status`)
      if (!res.ok) {
        if (res.status === 404) {
          throw new Error(`Device '${deviceId}' not registered in registry mapping.`)
        }
        throw new Error('Failed to fetch status')
      }
      const data = await res.json()
      setState(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Effect for SSE stream and initial fetch
  useEffect(() => {
    fetchStatus()

    // 1. Live real-time stream using Server-Sent Events (SSE)
    const API_BASE = import.meta.env.VITE_API_BASE || '/api'
    const stream = new EventSource(`${API_BASE}/stream`)

    const handleStreamUpdate = () => {
      // Re-fetch status immediately when an incident updates, opens or resolves
      fetchStatus()
    }

    // Listen to all relevant server-broadcast events
    stream.addEventListener('incident_new', handleStreamUpdate)
    stream.addEventListener('incident_updated', handleStreamUpdate)
    stream.addEventListener('incident_resolved', handleStreamUpdate)
    stream.addEventListener('message', handleStreamUpdate)

    stream.onerror = () => {
      // SSE connection error (e.g. backend restarting). Fallback will handle it.
    }

    // 2. 5-second polling backup for kiosk screen robustness
    const pollInterval = setInterval(fetchStatus, 5000)

    return () => {
      stream.close()
      clearInterval(pollInterval)
    }
  }, [deviceId])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-slate-900 text-slate-100 font-sans p-6">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500 mb-4"></div>
        <div className="text-xl font-medium tracking-wide">Starting Kiosk Display...</div>
        <div className="text-sm text-slate-400 mt-2">Connecting to Alerting Backend</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-slate-950 text-rose-500 font-sans p-6 text-center">
        <AlertTriangle size={64} className="mb-4 animate-bounce" />
        <h1 className="text-3xl font-bold tracking-tight mb-2">Display Registry Error</h1>
        <p className="text-slate-400 max-w-md mx-auto text-lg mb-6">{error}</p>
        <div className="text-xs text-slate-600 font-mono">
          Device ID: {deviceId} | Host: {window.location.host}
        </div>
      </div>
    )
  }

  const { status, incident } = state

  // Render CLEAR (No active alerts) state
  if (status === 'CLEAR') {
    return (
      <div className="flex flex-col min-h-screen bg-slate-950 text-slate-100 font-sans select-none overflow-hidden">
        {/* Top bar */}
        <div className="bg-slate-900/80 border-b border-slate-800 px-8 py-5 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <span className="h-3.5 w-3.5 rounded-full bg-emerald-500 animate-ping"></span>
            <span className="text-xl font-bold tracking-wider text-emerald-400 uppercase">DIALOG SMART ALERTS</span>
          </div>
          <div className="text-slate-400 font-mono text-xl flex items-center gap-2">
            <Clock size={20} className="text-slate-500" />
            {currentTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </div>
        </div>

        {/* Main Content */}
        <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
          <div className="relative mb-8">
            <div className="absolute inset-0 bg-emerald-500/20 rounded-full blur-3xl scale-150 animate-pulse"></div>
            <div className="relative bg-emerald-950/40 border-2 border-emerald-500/30 p-10 rounded-full text-emerald-400">
              <ShieldCheck size={120} className="stroke-[1.5]" />
            </div>
          </div>

          <h1 className="text-5xl font-extrabold tracking-tight text-white mb-4">
            Monitoring Area
          </h1>
          <p className="text-2xl text-slate-300 max-w-2xl leading-relaxed">
            No active elephant alerts in this road sector.
          </p>
        </div>

        {/* Footer */}
        <div className="bg-slate-900/40 border-t border-slate-900/60 px-8 py-5 flex justify-between items-center text-sm text-slate-500">
          <div>Display: <span className="font-mono text-slate-300">{deviceId}</span></div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-500"></span>
            System Live & Connected
          </div>
        </div>
      </div>
    )
  }

  // Render ALERT state (Flashing emergency screen)
  const openedDate = incident ? new Date(incident.opened_at) : null
  const localTime = openedDate ? openedDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''

  return (
    <div className="flex flex-col min-h-screen bg-rose-950 font-sans select-none overflow-hidden animate-pulse-emergency">
      {/* 1. Safety Message Top Banner */}
      <div className="bg-gradient-to-r from-red-600 via-orange-600 to-red-600 border-b-4 border-yellow-500 px-8 py-5 text-center shadow-xl z-10">
        <h1 className="text-4xl md:text-5xl font-black tracking-wider text-white uppercase animate-pulse">
          ⚠️ ELEPHANT DETECTED - STAY AWAY FROM THIS AREA
        </h1>
      </div>

      {/* 2. Main Image Section (Most of screen, but not full screen) */}
      <div className="flex-1 flex items-center justify-center p-6 md:p-8">
        <div className="relative w-full max-w-7xl h-[65vh] rounded-3xl overflow-hidden shadow-2xl border-4 border-rose-500/30 bg-slate-900">
          {/* Main Elephant Image */}
          <div 
            className="absolute inset-0 bg-cover bg-center scale-105"
            style={{ backgroundImage: `url('/uploads/elephant_warning.jpg')` }}
          />
          {/* Dark Overlay + Blur Effect */}
          <div className="absolute inset-0 bg-black/45 backdrop-blur-[2px]" />

          {/* 3. Center Warning Icon (Pulsing and Glowing) */}
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="relative flex items-center justify-center">
              <div className="absolute inset-0 rounded-full bg-yellow-500/20 blur-3xl scale-[2] animate-pulse-glow" />
              <div className="bg-yellow-500 text-slate-950 p-7 md:p-9 rounded-full shadow-2xl animate-bounce-slow border-4 border-yellow-400">
                <AlertTriangle size={80} className="stroke-[2.5]" />
              </div>
            </div>
          </div>

          {/* Location Area Text Overlaid Bottom-Left */}
          <div className="absolute bottom-6 left-8 text-white text-shadow-emergency">
            <div className="text-sm font-semibold uppercase tracking-widest text-rose-300">Detection Sector</div>
            <div className="text-3xl md:text-4xl font-extrabold">{incident.zone_name}</div>
          </div>
        </div>
      </div>

      {/* 4. Detection Information Panel at the bottom */}
      <div className="bg-slate-950/90 border-t-4 border-rose-600 px-10 py-6 md:py-8 grid grid-cols-3 gap-6 md:gap-12 text-slate-100 z-10 backdrop-blur-md">
        
        {/* Station ID */}
        <div className="flex items-center gap-4 border-r border-slate-800 pr-6">
          <div className="bg-rose-950/60 p-3 rounded-xl border border-rose-500/20 text-rose-400">
            <Radio size={28} />
          </div>
          <div>
            <div className="text-xs font-bold uppercase tracking-widest text-slate-500">Station ID</div>
            <div className="text-2xl md:text-3xl font-mono font-black text-white">{incident.station_id || 'Unknown'}</div>
          </div>
        </div>

        {/* Detection Time */}
        <div className="flex items-center gap-4 border-r border-slate-800 pr-6">
          <div className="bg-rose-950/60 p-3 rounded-xl border border-rose-500/20 text-rose-400">
            <Clock size={28} />
          </div>
          <div>
            <div className="text-xs font-bold uppercase tracking-widest text-slate-500">Detection Time</div>
            <div className="text-2xl md:text-3xl font-black text-white">{localTime}</div>
          </div>
        </div>

        {/* Confidence Level */}
        <div className="flex items-center gap-4">
          <div className="bg-rose-950/60 p-3 rounded-xl border border-rose-500/20 text-rose-400">
            <Activity size={28} />
          </div>
          <div>
            <div className="text-xs font-bold uppercase tracking-widest text-slate-500">Confidence Level</div>
            <div className="text-2xl md:text-3xl font-mono font-black text-yellow-400">
              {Math.round(incident.confidence)}%
            </div>
          </div>
        </div>

      </div>

      {/* Footer Info */}
      <div className="bg-slate-900 border-t border-slate-800 px-10 py-4 flex justify-between items-center text-xs text-slate-500">
        <div>Kiosk Unit: <span className="font-mono text-slate-300">{deviceId}</span></div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-rose-500 animate-ping"></span>
          Emergency Broadcasting Mode
        </div>
      </div>

      <style>{`
        .animate-pulse-emergency {
          animation: pulse-bg 2.5s infinite alternate;
        }
        @keyframes pulse-bg {
          0% { background-color: #3b0712; }
          100% { background-color: #5c071a; }
        }
        .animate-pulse-glow {
          animation: pulse-glow 1.5s infinite alternate;
        }
        @keyframes pulse-glow {
          0% { opacity: 0.2; transform: scale(1.5); }
          100% { opacity: 0.6; transform: scale(2.5); }
        }
        .animate-bounce-slow {
          animation: bounce-slow 2s infinite;
        }
        @keyframes bounce-slow {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-8px); }
        }
        .text-shadow-emergency {
          text-shadow: 0 4px 10px rgba(0, 0, 0, 0.8);
        }
      `}</style>
    </div>
  )
}
