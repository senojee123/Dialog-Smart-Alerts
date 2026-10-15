import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { SkipForward, Volume2, VolumeX } from 'lucide-react'
import { narrate, cancel as cancelSpeech, splitSentences, speechSupported } from './narrator.js'
import { useTargetRect, Spotlight, TourCard, CtrlButton } from './TourChrome.jsx'

/**
 * Live narration — presenter mode on REAL data.
 *
 * Plays a short intro, then listens: it polls the live API and, when a real
 * alert arrives (new incident, escalation to critical, road signs lighting,
 * resolution), queues a narrated, spotlighted walkthrough built from that
 * alert's actual values. Anything already open when it starts is the baseline
 * and is never narrated.
 */

const POLL_MS = 2500
const ACTIVE = new Set(['ACTIVE', 'OPERATOR_REVIEW'])
const CHANNEL_WORD = { sms: 'SMS', whatsapp: 'WhatsApp', email: 'email', push: 'app notification', voice: 'voice call', radio: 'radio' }
const NUM_WORD = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

const INTRO = [
  {
    key: 'intro-1', route: '/', title: 'Live from the field',
    text: () => 'Welcome to Dialog Smart Alerts. Everything you are about to see is live. ' +
                'The platform is connected to the cameras on the elephant corridor, and I will describe each alert the moment it arrives.',
  },
  {
    key: 'intro-2', route: '/', target: 'kpis', title: 'Listening for elephants',
    text: () => 'These numbers are live. The system is now watching for the next elephant detection. ' +
                'As soon as a camera spots one, I will walk you through exactly what happens.',
  },
]

async function getJSON(path) {
  const res = await fetch(path)
  if (!res.ok) throw new Error(String(res.status))
  return res.json()
}

const listWords = (xs) => xs.length <= 1 ? (xs[0] || '') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`
const num = (n) => NUM_WORD[n] ?? String(n)
const selectIncident = (id) => window.dispatchEvent(new CustomEvent('tour:select-incident', { detail: id }))

function playChime() {
  try {
    const ctx = new AudioContext()
    ;[[660, 0], [880, 0.18]].forEach(([f, at]) => {
      const osc = ctx.createOscillator(), gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.value = f
      osc.connect(gain); gain.connect(ctx.destination)
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + at)
      gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + at + 0.03)
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.55)
      osc.start(ctx.currentTime + at)
      osc.stop(ctx.currentTime + at + 0.6)
    })
    setTimeout(() => ctx.close(), 1500)
  } catch { /* audio unavailable */ }
}

export default function LiveNarrator({ muted, setMuted, onExit }) {
  const navigate = useNavigate()
  // Narration queue; the head is what's on screen. Plain state (no effect
  // shifting) so it stays correct under StrictMode's double effects.
  const [queue, setQueue] = useState(INTRO)
  const item = queue[0] ?? null
  const [sentences, setSentences] = useState([])
  const [sentence, setSentence] = useState(0)
  const [speaking, setSpeaking] = useState(false)
  const [conn, setConn] = useState('connecting')    // connecting | live | offline
  const [alerts, setAlerts] = useState(0)
  const [listenSince, setListenSince] = useState(Date.now())
  const [, setClock] = useState(0)

  // Latest incident data by id, so narration text is built at speak time.
  const incRef = useRef(new Map())
  const devNameRef = useRef({})

  const enqueue = useCallback((...items) => setQueue(q => [...q, ...items]), [])

  // ── narration text from real data ──────────────────────────────────────────
  const inc = (id) => incRef.current.get(id) || {}
  const zoneOf = (i) => i.zone || i.zone_name || 'the corridor'
  const objectOf = (i) => (!i.object || i.object === 'unknown') ? 'elephant' : String(i.object).toLowerCase()
  const pctOf = (i) => Math.round((i.confidence <= 1 ? i.confidence * 100 : i.confidence) || 0)

  const newIncidentItems = (id) => [
    {
      key: `new-${id}`, alert: true, route: '/', target: 'recent-incidents', title: 'Live alert: elephant detected',
      text: () => {
        const i = inc(id)
        const dev = devNameRef.current[i.device_id] || 'a roadside camera'
        const conf = pctOf(i) ? `, with ${pctOf(i)} percent confidence` : ''
        const crit = i.severity === 'CRITICAL' ? ', and it is already marked critical' : ''
        return `An ${objectOf(i)} has just been detected by ${dev} on the ${zoneOf(i)}${conf}. ` +
               `An incident was opened automatically${crit}. Nobody had to press a button.`
      },
    },
    {
      key: `resp-${id}`, route: '/incidents', target: 'incident-detail', title: 'Responders alerted',
      onEnter: () => selectIncident(id),
      text: () => {
        const s = inc(id).stakeholders || []
        const names = s.map(x => x.name).filter(Boolean)
        const chans = [...new Set(s.flatMap(x => (x.channels || []).map(c => CHANNEL_WORD[c.type] || c.type)))]
        const who = names.length
          ? `${listWords(names)} ${names.length === 1 ? 'has' : 'have'} been alerted${chans.length ? ` by ${listWords(chans)}` : ''}.`
          : 'The responders for this corridor are being alerted now.'
        return `${who} The camera evidence, and every action the system has taken, are recorded here.`
      },
    },
  ]

  const escalationItem = (id) => ({
    key: `crit-${id}-${Date.now()}`, alert: true, route: '/incidents', target: 'incident-detail',
    title: 'Confirmed: escalated to critical', onEnter: () => selectIncident(id),
    text: () => `Another detection has confirmed the sighting on the ${zoneOf(inc(id))}. ` +
                'The incident is now critical, and the escalation has gone out to the response team.',
  })

  const resolvedItem = (id) => ({
    key: `done-${id}-${Date.now()}`, route: '/', target: 'recent-incidents', title: 'All clear',
    text: () => `The incident on the ${zoneOf(inc(id))} has been ${inc(id).status === 'CLOSED' ? 'closed by the operator' : 'resolved'}. ` +
                'The corridor is back to normal monitoring.',
  })

  const signsItem = (n) => ({
    key: `signs-${Date.now()}`, route: '/road-signs', target: 'sign-grid', title: 'Drivers warned',
    text: () => `${num(n).replace(/^./, c => c.toUpperCase())} road sign${n === 1 ? '' : 's'} near the elephant ${n === 1 ? 'is' : 'are'} now warning drivers to slow down. ` +
                'As the elephant moves, the warning moves with it.',
  })

  // ── watcher ─────────────────────────────────────────────────────────────────
  useEffect(() => {
    let stopped = false, timer
    const known = new Map()         // id → { severity, status }
    let baselined = false
    let prevWarn = null

    getJSON('/api/devices')
      .then(ds => { devNameRef.current = Object.fromEntries((ds || []).map(d => [d.id, d.name || d.id])) })
      .catch(() => {})

    const poll = async () => {
      try {
        const [incidents, signs] = await Promise.all([
          getJSON('/api/incidents'),
          getJSON('/api/road-signs').catch(() => null),
        ])
        if (stopped) return
        setConn('live')
        incidents.forEach(i => incRef.current.set(i.incident_id || i.id, i))
        const warn = Array.isArray(signs) ? signs.filter(s => s.state === 'WARNING').length : null

        if (!baselined) {
          incidents.forEach(i => known.set(i.incident_id || i.id, { severity: i.severity, status: i.status }))
          prevWarn = warn
          baselined = true
        } else {
          const ordered = [...incidents].sort((a, b) => new Date(a.opened_at) - new Date(b.opened_at))
          for (const i of ordered) {
            const id = i.incident_id || i.id
            const k = known.get(id)
            if (!k) {
              if (ACTIVE.has(i.status)) { enqueue(...newIncidentItems(id)); setAlerts(n => n + 1) }
            } else if (ACTIVE.has(k.status) && !ACTIVE.has(i.status)) {
              enqueue(resolvedItem(id))
            } else if (k.severity !== 'CRITICAL' && i.severity === 'CRITICAL' && ACTIVE.has(i.status)) {
              enqueue(escalationItem(id))
            }
            known.set(id, { severity: i.severity, status: i.status })
          }
          if (warn != null && prevWarn === 0 && warn > 0) enqueue(signsItem(warn))
          if (warn != null) prevWarn = warn
        }
      } catch {
        if (!stopped) setConn('offline')
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS)
    }
    poll()
    return () => { stopped = true; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enqueue])

  // Keep the screen awake while presenting.
  useEffect(() => {
    let lock
    navigator.wakeLock?.request('screen').then(l => { lock = l }).catch(() => {})
    return () => { lock?.release?.().catch?.(() => {}) }
  }, [])

  // Waiting clock.
  useEffect(() => {
    if (item) return
    const t = setInterval(() => setClock(c => c + 1), 1000)
    return () => clearInterval(t)
  }, [item])

  // ── queue → presentation ───────────────────────────────────────────────────
  // Drop the head only if it's still `key` (skip + timer can't double-advance).
  const finishItem = useCallback((key) => {
    setSpeaking(false)
    setQueue(q => (q[0]?.key === key ? q.slice(1) : q))
  }, [])

  useEffect(() => { if (!item) setListenSince(Date.now()) }, [item])

  useEffect(() => {
    if (!item) return
    if (item.route) navigate(item.route)
    if (item.alert) playChime()
    const enter = setTimeout(() => item.onEnter?.(), 350)

    const text = item.text()
    const ss = splitSentences(text)
    setSentences(ss)
    setSentence(0)
    setSpeaking(!muted)
    let stop = () => {}, after
    const lead = setTimeout(() => {
      stop = narrate(text, {
        muted,
        onSentence: setSentence,
        onDone: () => { setSpeaking(false); after = setTimeout(() => finishItem(item.key), 1600) },
      })
    }, item.alert ? 900 : 650)
    return () => { clearTimeout(enter); clearTimeout(lead); clearTimeout(after); stop() }
    // Mute changes take effect from the next item.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item])

  const skip = useCallback(() => { cancelSpeech(); if (item) finishItem(item.key) }, [finishItem, item])

  // Keyboard: Esc exits, → skips the current narration.
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest?.('input, textarea, select')) return
      if (e.key === 'Escape') onExit()
      else if (e.key === 'ArrowRight' && item) skip()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [item, onExit, skip])

  const rect = useTargetRect(item?.target, item?.key)
  const listening = !item
  const waited = Math.floor((Date.now() - listenSince) / 1000)
  const waitedLabel = `${Math.floor(waited / 60)}:${String(waited % 60).padStart(2, '0')}`

  const controls = (
    <div className="mt-4 flex items-center gap-2">
      {speechSupported() && (
        <CtrlButton title={muted ? 'Turn narration on' : 'Mute narration'} onClick={() => setMuted(m => !m)}>
          {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </CtrlButton>
      )}
      {!listening && (
        <CtrlButton title="Skip (→)" onClick={skip}><SkipForward size={16} /></CtrlButton>
      )}
      <button
        onClick={onExit}
        className="ml-auto px-4 py-2 rounded-md border border-line text-sm font-semibold text-ink-muted hover:text-ink hover:bg-surface-alt"
      >
        End live mode
      </button>
    </div>
  )

  return (
    <div className="fixed inset-0 z-[3000] pointer-events-none" aria-live="polite">
      {/* While listening the page stays fully visible — no dimming. */}
      {!listening && <Spotlight rect={item.target ? rect : null} />}

      {listening ? (
        <TourCard label="Live narration" title="Listening for live detections" speaking={false} onExit={onExit}>
          <div className="mt-2 flex items-center gap-2 text-[13px]">
            <span className="relative flex h-2.5 w-2.5">
              {conn === 'live' && <span className="absolute inline-flex h-full w-full rounded-full bg-sev-low opacity-60 animate-ping" />}
              <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${conn === 'live' ? 'bg-sev-low' : conn === 'offline' ? 'bg-sev-critical' : 'bg-sev-medium'}`} />
            </span>
            <span className="text-ink">
              {conn === 'live' ? 'Connected to the field' : conn === 'offline' ? 'Reconnecting to the live system…' : 'Connecting…'}
            </span>
            <span className="ml-auto font-mono text-ink-subtle">{waitedLabel}</span>
          </div>
          <p className="mt-2 text-[12.5px] text-ink-muted leading-relaxed">
            Each new elephant alert will be announced and walked through automatically.
            {alerts > 0 && ` ${alerts} alert${alerts === 1 ? '' : 's'} narrated so far.`}
          </p>
          {controls}
        </TourCard>
      ) : (
        <TourCard
          rect={item.target ? rect : null} centred={!item.target}
          label={item.alert ? 'Live alert' : 'Live narration'}
          title={item.title} sentences={sentences} sentence={sentence}
          speaking={speaking && !muted} onExit={onExit}
        >
          {controls}
        </TourCard>
      )}
    </div>
  )
}
