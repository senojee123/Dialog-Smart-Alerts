import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Pause, Play, Volume2, VolumeX, Headphones } from 'lucide-react'
import { TOURS } from './steps.js'
import { startDemo, stopDemo } from './demoStore.js'
import { narrate, cancel as cancelSpeech, splitSentences, speechSupported } from './narrator.js'
import { useTargetRect, Spotlight, TourCard, CtrlButton } from './TourChrome.jsx'
import LiveNarrator from './LiveNarrator.jsx'

const TourContext = createContext({ start: () => {}, active: false })
export const useTour = () => useContext(TourContext)

/** Menu entries, in display order. */
export const TOUR_OPTIONS = [
  { id: 'executive', label: 'Executive Tour', hint: 'About 2 minutes' },
  { id: 'full',      label: 'Full Tour',      hint: 'Every feature, about 7 minutes' },
  { id: 'live',      label: 'Live Narration', hint: 'Narrates real alerts as they arrive' },
]

export default function TourProvider({ children }) {
  const [active, setActive] = useState(false)
  const [variant, setVariant] = useState('executive')
  const [index, setIndex]   = useState(0)
  const [playing, setPlaying] = useState(true)
  const [muted, setMuted]   = useState(false)

  const start = useCallback((which = 'executive') => {
    const v = which === 'live' || TOURS[which] ? which : 'executive'
    setVariant(v)
    // Scripted tours play their own scenario; live narration reads real data.
    if (v === 'live') stopDemo(); else startDemo()
    setIndex(0)
    setPlaying(true)
    setActive(true)
  }, [])

  const exit = useCallback(() => {
    cancelSpeech()
    stopDemo()
    setActive(false)
  }, [])

  return (
    <TourContext.Provider value={{ start, active }}>
      {children}
      {active && variant === 'live' && (
        <LiveNarrator muted={muted} setMuted={setMuted} onExit={exit} />
      )}
      {active && variant !== 'live' && (
        <TourOverlay
          key={variant}
          tour={TOURS[variant]}
          index={index} setIndex={setIndex}
          playing={playing} setPlaying={setPlaying}
          muted={muted} setMuted={setMuted}
          onExit={exit}
        />
      )}
    </TourContext.Provider>
  )
}

// ── scripted tour overlay ────────────────────────────────────────────────────

function TourOverlay({ tour, index, setIndex, playing, setPlaying, muted, setMuted, onExit }) {
  const navigate = useNavigate()
  const location = useLocation()
  const steps = tour.steps
  const step = steps[index]
  const sentences = splitSentences(step.text)
  const isLast = index === steps.length - 1

  const rect = useTargetRect(step.target, step.id)
  const [sentence, setSentence] = useState(0)
  const [speaking, setSpeaking] = useState(false)
  const firedRef = useRef(new Set())       // actions fired this run
  const narrDoneRef = useRef(false)
  const minUntilRef = useRef(0)
  const sentenceRef = useRef(0)
  const advanceTimer = useRef(null)

  const go = useCallback((i) => {
    cancelSpeech()
    if (i < 0) return
    if (i >= steps.length) { onExit(); return }
    setIndex(i)
  }, [onExit, setIndex, steps.length])

  // Route for this step.
  useEffect(() => {
    if (step.route && location.pathname !== step.route) navigate(step.route)
  }, [step, location.pathname, navigate])

  // Per-step hooks.
  useEffect(() => {
    sentenceRef.current = 0
    setSentence(0)
    narrDoneRef.current = false
    minUntilRef.current = Date.now() + (step.minMs || 0)
    const t = setTimeout(() => step.onEnter?.(), 350)
    return () => clearTimeout(t)
  }, [step])

  const fireAction = useCallback((sIdx) => {
    if (!step.action || firedRef.current.has(step.id)) return
    if (sIdx >= (step.actionAt ?? 0)) {
      firedRef.current.add(step.id)
      step.action()
    }
  }, [step])

  const scheduleAdvance = useCallback(() => {
    clearTimeout(advanceTimer.current)
    const wait = Math.max(1400, minUntilRef.current - Date.now())
    advanceTimer.current = setTimeout(() => go(index + 1), wait)
  }, [go, index])

  // Narration: (re)starts on step change, play/pause and mute — resuming from
  // the current sentence.
  useEffect(() => {
    clearTimeout(advanceTimer.current)
    if (!playing) { cancelSpeech(); setSpeaking(false); return }
    if (narrDoneRef.current) { scheduleAdvance(); return }

    const from = sentenceRef.current
    const rest = sentences.slice(from).join(' ')
    setSpeaking(!muted)
    // Small lead-in so the page/route settles before speaking.
    let stop = () => {}
    const lead = setTimeout(() => {
      stop = narrate(rest, {
        muted,
        onSentence: (i) => {
          const abs = from + i
          sentenceRef.current = abs
          setSentence(abs)
          fireAction(abs)
        },
        onDone: () => {
          narrDoneRef.current = true
          setSpeaking(false)
          fireAction(Infinity)
          if (!isLast) scheduleAdvance()
        },
      })
    }, from === 0 ? 650 : 100)
    return () => { clearTimeout(lead); stop(); clearTimeout(advanceTimer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, playing, muted])

  // Keyboard: ← → navigate, space pauses, Esc exits.
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest?.('input, textarea, select')) return
      if (e.key === 'Escape') onExit()
      else if (e.key === 'ArrowRight') go(index + 1)
      else if (e.key === 'ArrowLeft') go(index - 1)
      else if (e.key === ' ') { e.preventDefault(); setPlaying(p => !p) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, index, onExit, setPlaying])

  const centred = !step.target || !rect

  return (
    <div className="fixed inset-0 z-[3000] pointer-events-none" aria-live="polite">
      <Spotlight rect={centred ? null : rect} />

      <TourCard
        rect={rect} centred={centred}
        label={tour.label} counter={`${index + 1} / ${steps.length}`}
        progress={(index + 1) / steps.length}
        title={step.title} sentences={sentences} sentence={sentence}
        speaking={speaking && playing && !muted}
        onExit={onExit}
      >
        <div className="mt-4 flex items-center gap-2">
          <CtrlButton title="Previous (←)" onClick={() => go(index - 1)} disabled={index === 0}>
            <ChevronLeft size={16} />
          </CtrlButton>
          <CtrlButton title={playing ? 'Pause (Space)' : 'Play (Space)'} onClick={() => setPlaying(p => !p)}>
            {playing ? <Pause size={16} /> : <Play size={16} />}
          </CtrlButton>
          {speechSupported() && (
            <CtrlButton title={muted ? 'Turn narration on' : 'Mute narration'} onClick={() => setMuted(m => !m)}>
              {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
            </CtrlButton>
          )}
          <button
            onClick={() => (isLast ? onExit() : go(index + 1))}
            className="ml-auto inline-flex items-center gap-1.5 px-4 py-2 rounded-md bg-brand text-white text-sm font-semibold hover:bg-brand-hover"
          >
            {isLast ? 'Finish' : index === 0 ? 'Start' : 'Next'}
            {!isLast && <ChevronRight size={15} />}
          </button>
        </div>

        {index === 0 && tour.hints && (
          <p className="mt-3 text-[11px] text-ink-subtle flex items-center gap-1.5">
            <Headphones size={12} /> Best with sound on · ← → to navigate · Space to pause · Esc to exit
          </p>
        )}
      </TourCard>
    </div>
  )
}
