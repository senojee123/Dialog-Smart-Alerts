import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'

// Shared presentation for the scripted tours and live narration: the
// spotlight that follows a [data-tour] target, and the caption card.

export const CARD_W = 380
const GAP = 16
const PAD = 8 // spotlight padding around the target

function findTarget(id) {
  return id ? document.querySelector(`[data-tour="${id}"]`) : null
}

/**
 * Viewport rect of `[data-tour=target]`, tracked as it mounts, moves or resizes.
 * Scrolls it into view once per `key` (i.e. per step).
 */
export function useTargetRect(target, key) {
  const [rect, setRect] = useState(null)
  useEffect(() => {
    let timer, last = '', scrolled = false
    const tick = () => {
      const el = findTarget(target)
      if (el) {
        if (!scrolled) { el.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); scrolled = true }
        const r = el.getBoundingClientRect()
        const vw = window.innerWidth, vh = window.innerHeight
        const box = {
          top: Math.max(4, r.top - PAD), left: Math.max(4, r.left - PAD),
          width: Math.min(vw - 8, r.width + PAD * 2), height: Math.min(vh - 8, r.height + PAD * 2),
        }
        const k = `${box.top|0},${box.left|0},${box.width|0},${box.height|0}`
        if (k !== last) { last = k; setRect(box) }
      } else if (last !== 'none') {
        last = 'none'
        setRect(null)
      }
      timer = setTimeout(tick, 120)
    }
    tick()
    return () => clearTimeout(timer)
  }, [target, key])
  return target ? rect : null
}

/** Dimmed page with a cut-out (or a full dim when `rect` is null). */
export function Spotlight({ rect }) {
  if (!rect) return <div className="absolute inset-0 bg-[rgba(10,14,25,0.62)] animate-fade-in" />
  return (
    <div
      className="absolute rounded-xl tour-spotlight"
      style={{
        top: rect.top, left: rect.left, width: rect.width, height: rect.height,
        boxShadow: '0 0 0 9999px rgba(10,14,25,0.58)',
        transition: 'top .45s cubic-bezier(.4,0,.2,1), left .45s cubic-bezier(.4,0,.2,1), width .45s cubic-bezier(.4,0,.2,1), height .45s cubic-bezier(.4,0,.2,1)',
      }}
    />
  )
}

/**
 * Caption card. Placement: beside `rect` when given, centred when `centred`,
 * otherwise docked bottom-right.
 */
export function TourCard({ rect, centred, label, counter, progress, title, sentences, sentence, speaking, onExit, children }) {
  const ref = useRef(null)
  const [h, setH] = useState(260)
  useLayoutEffect(() => { if (ref.current) setH(ref.current.offsetHeight) })

  const vw = window.innerWidth, vh = window.innerHeight
  const w = Math.min(CARD_W, vw - 32)
  const style = centred
    ? { width: 460, maxWidth: 'calc(100vw - 32px)', left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }
    : rect
    ? { width: CARD_W, maxWidth: 'calc(100vw - 32px)', ...placeCard(rect, h), transition: 'top .45s ease, left .45s ease' }
    : { width: CARD_W, maxWidth: 'calc(100vw - 32px)', top: vh - h - 24, left: vw - w - 24, transition: 'top .45s ease, left .45s ease' }

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={`${label}: ${title}`}
      className="absolute pointer-events-auto bg-white rounded-xl shadow-modal border border-line overflow-hidden animate-slide-in"
      style={style}
    >
      {progress != null && (
        <div className="h-1 bg-surface-sunken">
          <div className="h-full bg-brand transition-all duration-500" style={{ width: `${progress * 100}%` }} />
        </div>
      )}
      <div className="p-4">
        <div className="flex items-center justify-between gap-3 mb-2">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-brand">{label}</span>
            {counter && <span className="text-[11px] text-ink-subtle font-mono">{counter}</span>}
          </div>
          <div className="flex items-center gap-2">
            <VoiceBars active={speaking} />
            <button onClick={onExit} className="text-ink-muted hover:text-ink p-1 rounded hover:bg-surface-alt" title="End (Esc)">
              <X size={16} />
            </button>
          </div>
        </div>

        <h3 className="text-base font-bold text-ink leading-snug">{title}</h3>
        {sentences?.length > 0 && (
          <p className="mt-2 text-[13.5px] leading-relaxed">
            {sentences.map((s, i) => (
              <span key={i} className={`transition-colors duration-300 ${i === sentence ? 'text-ink' : i < sentence ? 'text-ink-muted' : 'text-ink-subtle'}`}>
                {s}{' '}
              </span>
            ))}
          </p>
        )}
        {children}
      </div>
    </div>
  )
}

export function CtrlButton({ title, onClick, disabled, children }) {
  return (
    <button
      onClick={onClick} disabled={disabled} title={title}
      className="p-2 rounded-md border border-line text-ink-muted hover:text-ink hover:bg-surface-alt disabled:opacity-40 disabled:cursor-not-allowed"
    >{children}</button>
  )
}

/** Place the caption card beside the spotlight where it fits; else float bottom-right. */
function placeCard(r, h) {
  const vw = window.innerWidth, vh = window.innerHeight
  const w = Math.min(CARD_W, vw - 32)
  const clampTop  = (t) => Math.max(16, Math.min(vh - h - 16, t))
  const clampLeft = (l) => Math.max(16, Math.min(vw - w - 16, l))

  if (r.left + r.width + GAP + w <= vw - 16) return { top: clampTop(r.top), left: r.left + r.width + GAP }       // right
  if (r.top + r.height + GAP + h <= vh - 16) return { top: r.top + r.height + GAP, left: clampLeft(r.left) }     // below
  if (r.top - GAP - h >= 16)                 return { top: r.top - GAP - h, left: clampLeft(r.left) }            // above
  if (r.left - GAP - w >= 16)                return { top: clampTop(r.top), left: r.left - GAP - w }             // left
  return { top: vh - h - 24, left: vw - w - 24 }                                                                  // overlay corner
}

function VoiceBars({ active }) {
  return (
    <span className="flex items-end gap-[2px] h-3.5 w-4" aria-hidden="true">
      {[0, 1, 2, 3].map(i => (
        <span
          key={i}
          className={`w-[3px] rounded-full bg-brand ${active ? 'tour-voice-bar' : ''}`}
          style={{ height: active ? undefined : 3, animationDelay: `${i * 0.13}s`, opacity: active ? 1 : 0.35 }}
        />
      ))}
    </span>
  )
}
