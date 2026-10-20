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

// Executive-tour style intro; once a real incident arrives, whatever is still
// queued is dropped (except the mandatory devices line) so the live story
// starts straight away.
const INTRO = [
  {
    key: 'intro-welcome', intro: true, route: '/', title: 'Welcome to Dialog Smart Alerts',
    text: () => 'Dialog Smart Alerts is a unified alerting platform. ' +
                'It receives event triggers, and uses its built-in rules engine to launch coordinated action, in seconds. ' +
                'Everything you are about to see is live.',
  },
  {
    key: 'intro-devices', intro: true, mandatory: true, route: '/devices', target: 'device-table', title: 'Connected devices',
    text: () => 'The platform can be connected to various devices. ' +
                'For this demo, the camera in front of you is currently connected, and labelled as Yala Corridor.',
  },
  {
    key: 'intro-incidents', intro: true, route: '/incidents', target: 'incident-table', title: 'Live Incidents',
    text: () => 'The Live Incidents view is the operator\'s main workspace. ' +
                'Critical incidents are pinned to the top, with severity, confidence, and notification delivery, all updating live.',
  },
  {
    key: 'intro-detail', intro: true, route: '/incidents', target: 'incident-detail', title: 'The full picture',
    onEnter: () => selectIncident(latestIncidentId()),
    text: () => 'Opening an incident shows the full picture: the camera evidence, the confidence score, ' +
                'the rules that fired, and every responder who was alerted.',
  },
  {
    key: 'intro-people', intro: true, route: '/admin/stakeholders', target: 'main', title: 'Stakeholders',
    text: () => 'Stakeholders are managed centrally, each with their own preferred channels, such as SMS, WhatsApp, or email.',
  },
  {
    key: 'intro-listen', intro: true, route: '/', target: 'kpis', title: 'Listening for elephants',
    text: () => 'The system is now watching. ' +
                'As soon as the camera spots an elephant, I will show you exactly what happens.',
  },
]

async function getJSON(path) {
  const res = await fetch(path)
  if (!res.ok) throw new Error(String(res.status))
  return res.json()
}

const listWords = (xs) => xs.length <= 1 ? (xs[0] || '') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`
const selectIncident = (id) => id && window.dispatchEvent(new CustomEvent('tour:select-incident', { detail: id }))

// Most recent incident from the last poll, for showing the detail panel during the intro.
const latestIncidents = new Map()
const latestIncidentId = () => {
  const all = [...latestIncidents.values()]
  all.sort((a, b) => new Date(b.opened_at) - new Date(a.opened_at))
  return all[0] && (all[0].incident_id || all[0].id)
}

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
  const namedRef = useRef(new Map())      // incident id → responders already named
  const playedRef = useRef(new Set())     // keys already shown this session

  // Already narrated, or still waiting in `q`.
  const seen = (q, prefix) =>
    q.some(x => x.key.startsWith(prefix)) || [...playedRef.current].some(k => k.startsWith(prefix))

  // After the first critical: why it escalated, the record, the map, what's next, then the close.
  const wrapUp = (q, id) => seen(q, 'wrap-close') ? [] : [
    rulesItem,
    timelineItem(id),
    mapItem(id),
    signsItem,
    closeItem,
  ]

  const enqueue = useCallback((...items) => setQueue(q => [...q, ...items]), [])
  const enqueueCritical = useCallback((id, ...items) =>
    setQueue(q => { const next = [...q, ...items]; return [...next, ...wrapUp(next, id)] }), [])
  // A real incident cuts the intro short: the line on screen finishes, the rest is dropped.
  const enqueueIncident = useCallback((id, items, critical) => setQueue(q => {
    const next = [...q.slice(0, 1), ...q.slice(1).filter(x => !x.intro || x.mandatory), ...items]
    return critical ? [...next, ...wrapUp(next, id)] : next
  }), [])

  // ── narration text from real data ──────────────────────────────────────────
  const inc = (id) => incRef.current.get(id) || {}
  const zoneOf = (i) => i.zone || i.zone_name || 'corridor'
  const objectOf = (i) => (!i.object || i.object === 'unknown') ? 'elephant' : String(i.object).toLowerCase()
  const namesOf = (i) => (i.stakeholders || []).map(x => x.name).filter(Boolean)
  const pctOf = (i) => Math.round((i.confidence <= 1 ? i.confidence * 100 : i.confidence) || 0)

  const newIncidentItems = (id) => [
    {
      key: `new-${id}`, alert: true, route: '/', target: 'recent-incidents', title: 'A detection comes in',
      text: () => {
        const i = inc(id)
        const conf = pctOf(i) ? `, with ${pctOf(i)} percent confidence` : ''
        const crit = i.severity === 'CRITICAL' ? ', already marked critical' : ''
        const obj = objectOf(i)
        return `The camera on the ${zoneOf(i)} has just spotted ${/^[aeiou]/.test(obj) ? 'an' : 'a'} ${obj}${conf}. ` +
               `An incident opened automatically${crit}. Nobody had to press a button.`
      },
    },
    {
      key: `resp-${id}`, route: '/incidents', target: 'incident-stakeholders', title: 'The right people, instantly',
      onEnter: () => selectIncident(id),
      text: () => {
        const s = inc(id).stakeholders || []
        const names = namesOf(inc(id))
        namedRef.current.set(id, new Set(names))
        const chans = [...new Set(s.flatMap(x => (x.channels || []).map(c => CHANNEL_WORD[c.type] || c.type)))]
        const who = names.length
          ? ` Here, ${listWords(names)} ${names.length === 1 ? 'is' : 'are'} alerted${chans.length ? ` by ${listWords(chans)}` : ''}.`
          : ''
        return `Every stakeholder is notified instantly on their preferred channels, and each delivery is tracked here.${who}`
      },
    },
  ]

  const escalationItem = (id) => ({
    key: `crit-${id}-${Date.now()}`, alert: true, route: '/incidents', target: 'incident-detail',
    title: 'Confirmed and escalated', onEnter: () => selectIncident(id),
    text: () => {
      // Responders added by the escalation, e.g. the second responder.
      const named = namedRef.current.get(id) || new Set()
      const added = namesOf(inc(id)).filter(n => !named.has(n))
      namedRef.current.set(id, new Set([...named, ...added]))
      const who = added.length
        ? `${listWords(added)}, the second responder${added.length === 1 ? ', is' : 's, are'} now alerted as well.`
        : 'the second responder is now alerted as well.'
      return `A second detection confirms the sighting. The system escalates to critical on its own, and ${who}`
    },
  })

  const rulesItem = {
    key: 'rules', route: '/admin/rules', target: 'main', title: 'Configured, not coded',
    text: () => 'That escalation was driven by the rules engine, configured without a single line of code. ' +
                'A single detection raises a high alert, and a confirmed second detection escalates to critical, bringing in more responders.',
  }

  const timelineItem = (id) => ({
    key: `timeline-${id}`, route: '/incidents', target: 'incident-timeline', title: 'The whole story, recorded',
    onEnter: () => selectIncident(id),
    text: () => 'The timeline records the whole story, time-stamped: the first detection, the confirmation, and every alert sent. ' +
                'A complete audit trail, built automatically.',
  })

  const resolvedItem = (id) => ({
    key: `done-${id}-${Date.now()}`, route: '/', target: 'recent-incidents', title: 'All clear',
    text: () => (inc(id).status === 'CLOSED'
      ? 'The operator has closed the incident. The corridor is back to normal monitoring.'
      : 'The incident has been resolved. The corridor is back to normal monitoring.') +
      (playedRef.current.has('wrap-close') ? '' : ' Detect, decide, notify, and warn: automatically, in seconds, around the clock.'),
  })

  const mapItem = (id) => ({
    key: `map-${id}`, route: '/gis', target: 'main', title: 'GIS view',
    text: () => `The GIS view plots every incident on the map, including this one on the ${zoneOf(inc(id))}, ` +
                'so the operations centre sees all activity at a glance.',
  })

  // No signs are connected in this demo — presented as the next step.
  const signsItem = {
    key: 'signs', route: '/road-signs', target: 'sign-grid', title: 'Next: warning drivers too',
    text: () => 'The next step is smart road signs, for a complete end-to-end system. ' +
                'Signs near the elephant would warn drivers to slow down, and the warning would follow the elephant as it moves.',
  }

  const closeItem = {
    key: 'wrap-close', route: '/', title: 'Detect. Decide. Notify. Warn.',
    text: () => 'Once the danger passes, the incident is closed and the corridor returns to normal monitoring. ' +
                'Detect, decide, notify, and warn: automatically, in seconds, around the clock.',
  }

  // ── watcher ─────────────────────────────────────────────────────────────────
  useEffect(() => {
    let stopped = false, timer
    const known = new Map()         // id → { severity, status }
    let baselined = false

    getJSON('/api/devices')
      .then(ds => { devNameRef.current = Object.fromEntries((ds || []).map(d => [d.id, d.name || d.id])) })
      .catch(() => {})

    const poll = async () => {
      try {
        const incidents = await getJSON('/api/incidents')
        if (stopped) return
        setConn('live')
        incidents.forEach(i => incRef.current.set(i.incident_id || i.id, i))
        latestIncidents.clear()
        incidents.forEach(i => latestIncidents.set(i.incident_id || i.id, i))

        if (!baselined) {
          incidents.forEach(i => known.set(i.incident_id || i.id, { severity: i.severity, status: i.status }))
          baselined = true
        } else {
          const ordered = [...incidents].sort((a, b) => new Date(a.opened_at) - new Date(b.opened_at))
          for (const i of ordered) {
            const id = i.incident_id || i.id
            const k = known.get(id)
            if (!k) {
              if (ACTIVE.has(i.status)) { enqueueIncident(id, newIncidentItems(id), i.severity === 'CRITICAL'); setAlerts(n => n + 1) }
            } else if (ACTIVE.has(k.status) && !ACTIVE.has(i.status)) {
              enqueue(resolvedItem(id))
            } else if (k.severity !== 'CRITICAL' && i.severity === 'CRITICAL' && ACTIVE.has(i.status)) {
              enqueueCritical(id, escalationItem(id))
            }
            known.set(id, { severity: i.severity, status: i.status })
          }
        }
      } catch {
        if (!stopped) setConn('offline')
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS)
    }
    poll()
    return () => { stopped = true; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enqueue, enqueueCritical, enqueueIncident])

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
    playedRef.current.add(item.key)
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
