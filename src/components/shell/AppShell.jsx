import { useState, useRef } from 'react'
import { Outlet } from 'react-router-dom'
import TopBar from './TopBar.jsx'
import NavSidebar from './NavSidebar.jsx'

export default function AppShell() {
  const [muteAlerts, setMuteAlerts] = useState(false)
  const [streamStatus] = useState('live')
  const audioCtxRef = useRef(null)

  function playCriticalCue() {
    if (muteAlerts) return
    try {
      const ctx = audioCtxRef.current ?? new AudioContext()
      audioCtxRef.current = ctx
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.frequency.setValueAtTime(880, ctx.currentTime)
      gain.gain.setValueAtTime(0.3, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6)
      osc.start()
      osc.stop(ctx.currentTime + 0.6)
    } catch {
      // audio not available
    }
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar
        streamStatus={streamStatus}
        muteAlerts={muteAlerts}
        onToggleMute={() => setMuteAlerts(m => !m)}
      />
      <div className="flex flex-1 overflow-hidden">
        <NavSidebar />
        <main className="flex-1 overflow-auto bg-white">
          <Outlet context={{ playCriticalCue, muteAlerts }} />
        </main>
      </div>
    </div>
  )
}
