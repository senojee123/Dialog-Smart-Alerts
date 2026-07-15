import { useState, useEffect, useRef, useCallback } from 'react'
import { GitBranch, Radio, PlayCircle, Mail, MessageSquare, Monitor, Volume2, Info, CheckCircle2, ShieldAlert } from 'lucide-react'
import { useApi } from '../../hooks/useApi.js'
import { PageHeader, Card, Badge } from '../../components/admin/CrudShell.jsx'

export default function Workflows() {
  const { data: rules, loading, error } = useApi('/api/rules')
  const { data: useCases } = useApi('/api/use-cases')
  const { data: stakeholders } = useApi('/api/stakeholders')

  const containerRef = useRef(null)
  const [coords, setCoords] = useState({})
  const [activeNode, setActiveNode] = useState(null) // { type: 'trigger'|'rule'|'action', id: string }
  const [selectedRule, setSelectedRule] = useState(null)

  // Measure element coordinates for drawing curves
  const updateCoords = useCallback(() => {
    if (!containerRef.current) return
    const containerRect = containerRef.current.getBoundingClientRect()
    const newCoords = {}
    const elements = containerRef.current.querySelectorAll('[data-node-id]')
    
    elements.forEach(el => {
      const id = el.getAttribute('data-node-id')
      const rect = el.getBoundingClientRect()
      newCoords[id] = {
        left: {
          x: rect.left - containerRect.left,
          y: rect.top - containerRect.top + rect.height / 2
        },
        right: {
          x: rect.right - containerRect.left,
          y: rect.top - containerRect.top + rect.height / 2
        }
      }
    })
    setCoords(newCoords)
  }, [])

  // Recalculate coordinates when rules load or screen resizes
  useEffect(() => {
    updateCoords()
    window.addEventListener('resize', updateCoords)
    const timer = setTimeout(updateCoords, 500) // fallback delay to allow rendering to settle
    return () => {
      window.removeEventListener('resize', updateCoords)
      clearTimeout(timer)
    }
  }, [rules, updateCoords])

  // Helper to draw clean cubic bezier curves
  function drawCurve(fromPoint, toPoint) {
    if (!fromPoint || !toPoint) return ''
    const dx = Math.abs(toPoint.x - fromPoint.x) * 0.4
    const control1X = fromPoint.x + dx
    const control1Y = fromPoint.y
    const control2X = toPoint.x - dx
    const control2Y = toPoint.y
    return `M ${fromPoint.x} ${fromPoint.y} C ${control1X} ${control1Y}, ${control2X} ${control2Y}, ${toPoint.x} ${toPoint.y}`
  }

  // Pre-defined static triggers
  const TRIGGERS = [
    { id: 'trig-telemetry', label: 'Telemetry Ingestion', desc: 'MQTT Camera Traps', icon: Radio },
    { id: 'trig-simulator', label: 'Manual Override', desc: 'Simulator Tool UI', icon: PlayCircle },
  ]

  // Pre-defined static actions
  const ACTIONS = [
    { id: 'act-sms', label: 'SMS Notifications', desc: 'Ideabiz SMS Gateway API', icon: Mail },
    { id: 'act-signs', label: 'LED warning boards', desc: 'MQTT Actuator Sign Commands', icon: Monitor },
    { id: 'act-sirens', label: 'Audible Sirens', desc: 'MQTT Actuator Alarm Commands', icon: Volume2 },
    { id: 'act-map', label: 'Live Dashboard Sync', desc: 'FastAPI SSE Live Event Stream', icon: Info },
  ]

  // Determine if a connection line should be highlighted
  function getConnectionState(fromId, toId) {
    if (!activeNode) return 'normal'

    const { type, id } = activeNode

    // 1. Trigger highlight
    if (type === 'trigger') {
      if (fromId === id) return 'highlight'
      // If we are looking at the connection between a rule and an action, highlight it if the rule is active
      const rule = rules?.find(r => `rule-${r.id}` === fromId)
      if (rule && rule.active) {
        if (toId === 'act-map') return 'highlight'
        const hasSMS = (rule.actions?.on_trigger?.notify_stakeholder_ids?.length > 0) || (rule.actions?.on_confirm?.notify_stakeholder_ids?.length > 0)
        if (toId === 'act-sms' && hasSMS) return 'highlight'
        const hasInc = rule.actions?.on_trigger?.create_incident || rule.actions?.on_confirm?.create_incident
        if ((toId === 'act-signs' || toId === 'act-sirens') && hasInc) return 'highlight'
      }
      return 'dim'
    }

    // 2. Rule highlight
    if (type === 'rule') {
      const isThisRule = `rule-${id}` === fromId || `rule-${id}` === toId
      if (isThisRule) return 'highlight'
      return 'dim'
    }

    // 3. Action highlight
    if (type === 'action') {
      if (toId === id) return 'highlight'
      // Highlight incoming rule connection if it has the action wired up
      const rule = rules?.find(r => `rule-${r.id}` === fromId)
      if (rule && rule.active) {
        const hasSMS = (rule.actions?.on_trigger?.notify_stakeholder_ids?.length > 0) || (rule.actions?.on_confirm?.notify_stakeholder_ids?.length > 0)
        const hasInc = rule.actions?.on_trigger?.create_incident || rule.actions?.on_confirm?.create_incident
        if (toId === 'act-map' && id === 'act-map') return 'highlight'
        if (toId === 'act-sms' && id === 'act-sms' && hasSMS) return 'highlight'
        if ((toId === 'act-signs' || toId === 'act-sirens') && (id === 'act-signs' || id === 'act-sirens') && hasInc) return 'highlight'
      }
      return 'dim'
    }

    return 'normal'
  }

  // Get active node class states
  function getNodeState(nodeId, type) {
    if (!activeNode) return 'normal'
    if (activeNode.id === nodeId) return 'selected'

    const { type: activeType, id: activeId } = activeNode

    if (activeType === 'trigger') {
      if (type === 'trigger') return 'dim'
      if (type === 'rule') {
        const rule = rules?.find(r => r.id === nodeId.replace('rule-', ''))
        return rule?.active ? 'highlight' : 'dim'
      }
      if (type === 'action') {
        // Any action that has at least one active rule triggering it is highlighted
        const hasActiveConnection = rules?.some(rule => {
          if (!rule.active) return false
          const hasSMS = (rule.actions?.on_trigger?.notify_stakeholder_ids?.length > 0) || (rule.actions?.on_confirm?.notify_stakeholder_ids?.length > 0)
          const hasInc = rule.actions?.on_trigger?.create_incident || rule.actions?.on_confirm?.create_incident
          if (nodeId === 'act-map') return true
          if (nodeId === 'act-sms' && hasSMS) return true
          if ((nodeId === 'act-signs' || nodeId === 'act-sirens') && hasInc) return true
          return false
        })
        return hasActiveConnection ? 'highlight' : 'dim'
      }
    }

    if (activeType === 'rule') {
      const selectedRuleData = rules?.find(r => r.id === activeId)
      if (type === 'trigger') return 'highlight' // All triggers lead to this rule
      if (type === 'rule') return 'dim'
      if (type === 'action' && selectedRuleData?.active) {
        const hasSMS = (selectedRuleData.actions?.on_trigger?.notify_stakeholder_ids?.length > 0) || (selectedRuleData.actions?.on_confirm?.notify_stakeholder_ids?.length > 0)
        const hasInc = selectedRuleData.actions?.on_trigger?.create_incident || selectedRuleData.actions?.on_confirm?.create_incident
        if (nodeId === 'act-map') return 'highlight'
        if (nodeId === 'act-sms' && hasSMS) return 'highlight'
        if ((nodeId === 'act-signs' || nodeId === 'act-sirens') && hasInc) return 'highlight'
      }
      return 'dim'
    }

    if (activeType === 'action') {
      if (type === 'action') return 'dim'
      if (type === 'rule') {
        const rule = rules?.find(r => r.id === nodeId.replace('rule-', ''))
        if (rule?.active) {
          const hasSMS = (rule.actions?.on_trigger?.notify_stakeholder_ids?.length > 0) || (rule.actions?.on_confirm?.notify_stakeholder_ids?.length > 0)
          const hasInc = rule.actions?.on_trigger?.create_incident || rule.actions?.on_confirm?.create_incident
          if (activeId === 'act-map') return 'highlight'
          if (activeId === 'act-sms' && hasSMS) return 'highlight'
          if ((activeId === 'act-signs' || activeId === 'act-sirens') && hasInc) return 'highlight'
        }
        return 'dim'
      }
      if (type === 'trigger') {
        // Triggers are always highlight source for active actions
        return 'highlight'
      }
    }

    return 'normal'
  }

  function getLineStyles(state) {
    switch (state) {
      case 'highlight':
        return { stroke: 'var(--color-brand)', strokeWidth: 3.5, opacity: 1, filter: 'url(#glow)' }
      case 'dim':
        return { stroke: '#E4E7EC', strokeWidth: 1.5, opacity: 0.15 }
      default:
        return { stroke: '#D0D5DD', strokeWidth: 2, opacity: 0.6 }
    }
  }

  function getNodeClasses(state, baseColor = 'border-line') {
    const common = "p-4 rounded-xl border bg-white shadow-sm transition-all duration-300 relative cursor-pointer "
    switch (state) {
      case 'selected':
        return common + "border-brand ring-2 ring-brand/10 translate-x-1"
      case 'highlight':
        return common + "border-brand/40 shadow-md scale-[1.01] bg-brand/[0.01]"
      case 'dim':
        return common + "opacity-40 grayscale-[20%]"
      default:
        return common + `${baseColor} hover:border-line-strong hover:shadow-md hover:scale-[1.01]`
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden" ref={containerRef}>
      <PageHeader
        title="Workflow Visualizer"
        description="Interactive architecture diagram tracing live events from telemetry sensors, through evaluation rules, to warning alerts."
      />

      {/* Rules inspector / Detail Panel */}
      {selectedRule && (
        <div className="mx-6 mb-4 p-4 border border-brand/20 bg-brand/[0.02] rounded-xl flex items-start gap-4 shadow-sm animate-fade-in relative">
          <div className="p-2 bg-brand/5 rounded-lg text-brand shrink-0">
            <GitBranch size={20} />
          </div>
          <div className="flex-1 space-y-2">
            <div className="flex items-center gap-2">
              <h4 className="font-semibold text-ink text-sm">{selectedRule.name}</h4>
              <Badge color={selectedRule.active ? 'green' : 'gray'}>
                {selectedRule.active ? 'Active' : 'Disabled'}
              </Badge>
              <span className="text-xs text-ink-muted">· Priority {selectedRule.priority}</span>
            </div>
            {selectedRule.description && (
              <p className="text-xs text-ink-muted leading-relaxed">{selectedRule.description}</p>
            )}
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
              <div>
                <span className="text-[10px] font-bold text-ink-muted uppercase tracking-wider block mb-1">Trigger Conditions</span>
                <div className="space-y-1">
                  {(selectedRule.conditions || []).map((c, idx) => (
                    <span key={idx} className="inline-block text-[11px] bg-white border border-line rounded px-1.5 py-0.5 font-mono text-ink mr-1">
                      {c.field} {c.op} "{c.value}"
                    </span>
                  ))}
                </div>
              </div>
              
              <div>
                <span className="text-[10px] font-bold text-ink-muted uppercase tracking-wider block mb-1">Confirmation Details</span>
                {selectedRule.confirmation ? (
                  <div className="text-[11px] text-ink leading-relaxed">
                    Requires <span className="font-semibold">{selectedRule.confirmation.required_count} detections</span> within <span className="font-semibold">{selectedRule.confirmation.window_seconds / 60} minutes</span> (same zone).
                  </div>
                ) : (
                  <span className="text-[11px] text-ink-muted">Immediate action (no confirmation required).</span>
                )}
              </div>

              <div>
                <span className="text-[10px] font-bold text-ink-muted uppercase tracking-wider block mb-1">Alert Targets</span>
                <div className="text-[11px] text-ink space-y-0.5">
                  <div>Incident Creation: <span className="font-semibold">{selectedRule.actions?.on_trigger?.create_incident ? 'Enabled' : 'Disabled'}</span></div>
                  <div>Rangers Notified: <span className="font-semibold">
                    {selectedRule.actions?.on_trigger?.notify_stakeholder_ids?.length || 0} stakeholder(s)
                  </span></div>
                </div>
              </div>
            </div>
          </div>
          <button 
            onClick={() => { setSelectedRule(null); setActiveNode(null) }}
            className="absolute top-3 right-3 text-xs text-ink-muted hover:text-ink font-medium"
          >
            Clear selection
          </button>
        </div>
      )}

      {/* Interactive diagram area */}
      <div className="flex-1 overflow-auto p-6 relative select-none">
        
        {/* SVG background layer for connection lines */}
        <svg className="absolute inset-0 w-full h-full pointer-events-none z-0">
          <defs>
            <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Trigger ➔ Rule connections */}
          {coords && TRIGGERS.map(t => (
            rules?.map(r => {
              const state = getConnectionState(t.id, `rule-${r.id}`)
              const lineStyle = getLineStyles(state)
              return (
                <path
                  key={`${t.id}-${r.id}`}
                  d={drawCurve(coords[t.id]?.right, coords[`rule-${r.id}`]?.left)}
                  fill="none"
                  {...lineStyle}
                  className="transition-all duration-300"
                />
              )
            })
          ))}

          {/* Rule ➔ Action connections */}
          {coords && rules?.map(rule => (
            ACTIONS.map(action => {
              // Map dynamic action wiring logic
              let connected = false
              if (rule.active) {
                if (action.id === 'act-map') {
                  connected = true
                }
                if (action.id === 'act-sms') {
                  const hasSMS = (rule.actions?.on_trigger?.notify_stakeholder_ids?.length > 0) || (rule.actions?.on_confirm?.notify_stakeholder_ids?.length > 0)
                  if (hasSMS) connected = true
                }
                if (action.id === 'act-signs' || action.id === 'act-sirens') {
                  const hasInc = rule.actions?.on_trigger?.create_incident || rule.actions?.on_confirm?.create_incident
                  if (hasInc) connected = true
                }
              }

              if (!connected) return null

              const state = getConnectionState(`rule-${rule.id}`, action.id)
              const lineStyle = getLineStyles(state)
              return (
                <path
                  key={`${rule.id}-${action.id}`}
                  d={drawCurve(coords[`rule-${rule.id}`]?.right, coords[action.id]?.left)}
                  fill="none"
                  {...lineStyle}
                  className="transition-all duration-300"
                />
              )
            })
          ))}
        </svg>

        {/* 3-Column Node Layout */}
        <div className="grid grid-cols-3 gap-x-16 gap-y-6 max-w-6xl mx-auto h-full relative z-10">
          
          {/* Column 1: Triggers */}
          <div className="flex flex-col gap-6 justify-center">
            <h3 className="text-xs font-bold text-ink-muted uppercase tracking-wider mb-2 text-center">1. Intake Triggers</h3>
            {TRIGGERS.map(t => {
              const Icon = t.icon
              const state = getNodeState(t.id, 'trigger')
              return (
                <div
                  key={t.id}
                  data-node-id={t.id}
                  className={getNodeClasses(state, 'border-indigo-100')}
                  onClick={() => {
                    setActiveNode({ type: 'trigger', id: t.id })
                    setSelectedRule(null)
                  }}
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-indigo-50 text-indigo-600 rounded-lg">
                      <Icon size={18} />
                    </div>
                    <div>
                      <h4 className="font-semibold text-ink text-sm leading-snug">{t.label}</h4>
                      <p className="text-[11px] text-ink-muted leading-snug mt-0.5">{t.desc}</p>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Column 2: Rules Engine */}
          <div className="flex flex-col gap-6 justify-center">
            <h3 className="text-xs font-bold text-ink-muted uppercase tracking-wider mb-2 text-center">2. Processing Rules</h3>
            {loading && <div className="text-xs text-ink-muted text-center py-6">Loading rules...</div>}
            {error && <div className="text-xs text-sev-critical text-center py-6">Error loading rules.</div>}
            {!loading && !error && rules?.length === 0 && (
              <div className="text-xs text-ink-muted text-center py-6 border border-dashed border-line rounded-lg">No active rules.</div>
            )}
            {!loading && !error && rules?.map(r => {
              const state = getNodeState(`rule-${r.id}`, 'rule')
              const uc = useCases?.find(u => u.id === r.use_case_id)
              return (
                <div
                  key={r.id}
                  data-node-id={`rule-${r.id}`}
                  className={getNodeClasses(state, r.active ? 'border-amber-100' : 'border-line/40 opacity-60')}
                  onClick={() => {
                    setActiveNode({ type: 'rule', id: r.id })
                    setSelectedRule(r)
                  }}
                >
                  <div className="space-y-1">
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="font-semibold text-ink text-[13px] leading-tight line-clamp-1">{r.name}</h4>
                      <Badge color={r.active ? 'amber' : 'gray'}>P{r.priority}</Badge>
                    </div>
                    {uc && (
                      <span className="text-[10px] font-medium" style={{ color: uc.color }}>
                        {uc.name}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Column 3: Actions */}
          <div className="flex flex-col gap-6 justify-center">
            <h3 className="text-xs font-bold text-ink-muted uppercase tracking-wider mb-2 text-center">3. Output Actions</h3>
            {ACTIONS.map(a => {
              const Icon = a.icon
              const state = getNodeState(a.id, 'action')
              return (
                <div
                  key={a.id}
                  data-node-id={a.id}
                  className={getNodeClasses(state, 'border-rose-100')}
                  onClick={() => {
                    setActiveNode({ type: 'action', id: a.id })
                    setSelectedRule(null)
                  }}
                >
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-rose-50 text-rose-600 rounded-lg">
                      <Icon size={18} />
                    </div>
                    <div>
                      <h4 className="font-semibold text-ink text-sm leading-snug">{a.label}</h4>
                      <p className="text-[11px] text-ink-muted leading-snug mt-0.5">{a.desc}</p>
                    </div>
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
