import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { AlertTriangle, CheckCircle, WifiOff } from 'lucide-react'

// Same palette as RoadSignCard.jsx — keep these in sync.
const SIGN_STATE = {
  WARNING: { bg: '#D92D20', label: 'HAZARD AHEAD', sub: 'STOP / SLOW DOWN', pulse: true },
  CAUTION: { bg: '#F2841C', label: 'CAUTION',       sub: 'SLOW DOWN',        pulse: false },
  CLEAR:   { bg: '#15803d', label: 'ROAD CLEAR',    sub: '',                 pulse: false },
  OFFLINE: { bg: '#1e293b', label: 'OFFLINE',       sub: '',                 pulse: false },
}

export default function SignDisplay() {
  const { signId } = useParams()
  const [state, setState] = useState(null)
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const API_BASE = import.meta.env.VITE_API_BASE || '/api'

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/road-signs/${signId}/status`)
      if (!res.ok) {
        if (res.status === 404) {
          throw new Error(`Sign board '${signId}' is not registered.`)
        }
        throw new Error('Failed to fetch sign status')
      }
      const data = await res.json()
      setState(data.state || 'CLEAR')
      setName(data.name || signId)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()

    const stream = new EventSource(`${API_BASE}/stream`)
    const handleUpdate = () => fetchStatus()
    stream.addEventListener('signs_state', handleUpdate)
    stream.addEventListener('message', handleUpdate)
    stream.onerror = () => {}

    const pollInterval = setInterval(fetchStatus, 5000)

    return () => {
      stream.close()
      clearInterval(pollInterval)
    }
  }, [signId])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-slate-950 text-slate-100 font-sans">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-slate-400"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-slate-950 text-rose-500 font-sans p-6 text-center">
        <WifiOff size={56} className="mb-4" />
        <h1 className="text-2xl font-bold mb-2">Sign Display Error</h1>
        <p className="text-slate-400 max-w-md">{error}</p>
        <div className="text-xs text-slate-600 font-mono mt-4">Sign ID: {signId}</div>
      </div>
    )
  }

  const cfg = SIGN_STATE[state] || SIGN_STATE.CLEAR
  const isLit = state === 'WARNING' || state === 'CAUTION'
  const Icon = state === 'OFFLINE' ? WifiOff : isLit ? AlertTriangle : CheckCircle

  return (
    <div
      className="flex flex-col items-center justify-center min-h-screen select-none overflow-hidden transition-colors duration-700"
      style={{ background: cfg.bg }}
    >
      <Icon
        size={160}
        className={`text-white stroke-[1.5] ${cfg.pulse ? 'animate-pulse' : ''}`}
      />
      <h1 className="text-6xl font-black tracking-widest text-white mt-8 uppercase text-center px-8">
        {cfg.label}
      </h1>
      {cfg.sub && (
        <p className="text-3xl font-semibold text-white/90 mt-4 tracking-wide">{cfg.sub}</p>
      )}
    </div>
  )
}
