/**
 * Narrator — soft female voice-over via the browser's Speech Synthesis API.
 *
 * Picks the most natural female voice available (Edge/Windows "Natural"
 * neural voices first, then Google / macOS voices), speaks a little slower
 * and lower than default for a calm delivery, and splits text into sentences
 * (Chrome silently cuts utterances off after ~15 s otherwise). When speech is
 * unavailable or muted, it falls back to a reading-time timer so the tour
 * keeps its pace.
 */

const PREFERRED = [
  /aria.*natural/i, /jenny.*natural/i, /sonia.*natural/i, /libby.*natural/i, /natasha.*natural/i,
  /emma.*natural/i, /ava.*natural/i, /michelle.*natural/i, /clara.*natural/i,
  /google uk english female/i, /samantha/i, /serena/i, /karen/i, /moira/i, /tessa/i,
  /microsoft (aria|jenny|sonia|libby|hazel|susan|zira|heera|catherine)/i,
  /google us english/i, /female/i,
]

const synth = typeof window !== 'undefined' ? window.speechSynthesis : null
let voice = null
let session = 0

function pickVoice() {
  if (!synth) return null
  const voices = synth.getVoices().filter(v => /^en/i.test(v.lang))
  for (const re of PREFERRED) {
    const v = voices.find(x => re.test(x.name))
    if (v) return v
  }
  return voices[0] || null
}

if (synth) {
  voice = pickVoice()
  synth.addEventListener?.('voiceschanged', () => { voice = pickVoice() })
}

export function speechSupported() { return !!synth }
export function voiceName() { return voice?.name ?? null }

export function splitSentences(text) {
  return (text.match(/[^.!?]+[.!?]+["')\]]*|[^.!?]+$/g) || [text]).map(s => s.trim()).filter(Boolean)
}

/** Reading-time estimate (ms) for the silent fallback. */
export function readingTime(text) {
  const words = text.split(/\s+/).length
  return Math.max(2500, words * 390)
}

/**
 * Speak `text`. Calls onSentence(index) as each sentence starts and onDone()
 * when finished. Returns a cancel function. `muted` → timed, silent playback.
 */
export function narrate(text, { muted = false, onSentence, onDone } = {}) {
  cancel()
  const my = ++session
  const sentences = splitSentences(text)
  const alive = () => my === session

  if (muted || !synth) {
    let i = 0
    let t
    const step = () => {
      if (!alive()) return
      if (i >= sentences.length) { onDone?.(); return }
      onSentence?.(i)
      t = setTimeout(() => { i++; step() }, readingTime(sentences[i]))
    }
    step()
    return () => { clearTimeout(t); session++ }
  }

  if (!voice) voice = pickVoice()
  // Watchdog: if the engine stalls (no voices / blocked autoplay), keep moving.
  let watchdog
  const arm = (s) => {
    clearTimeout(watchdog)
    watchdog = setTimeout(() => { if (alive()) { synth.cancel(); next() } }, readingTime(s) * 2.2 + 2000)
  }

  let i = 0
  const next = () => {
    if (!alive()) return
    if (i >= sentences.length) { clearTimeout(watchdog); onDone?.(); return }
    const s = sentences[i]
    const u = new SpeechSynthesisUtterance(s)
    if (voice) { u.voice = voice; u.lang = voice.lang }
    u.rate = 0.94
    u.pitch = 1.08
    u.volume = 0.9
    const idx = i
    u.onstart = () => { if (alive()) onSentence?.(idx) }
    u.onend = () => { if (!alive()) return; i++; setTimeout(next, 160) }
    u.onerror = () => { if (!alive()) return; i++; next() }
    arm(s)
    synth.speak(u)
  }
  next()
  return () => { clearTimeout(watchdog); cancel() }
}

export function cancel() {
  session++
  try { synth?.cancel() } catch { /* ignore */ }
}

export function pause()  { try { synth?.pause() } catch { /* ignore */ } }
export function resume() { try { synth?.resume() } catch { /* ignore */ } }
