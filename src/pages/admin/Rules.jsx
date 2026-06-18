import { useState } from 'react'
import { Plus, Trash2, ChevronDown, ChevronUp, AlertTriangle, CheckCircle } from 'lucide-react'
import { useApi } from '../../hooks/useApi.js'
import {
  PageHeader, Btn, Badge, Table, SlideOver,
  Field, Input, Select, Textarea, SaveBar, ConfirmDialog, ErrorBanner,
} from '../../components/admin/CrudShell.jsx'

// ── Rule form blank ──────────────────────────────────────────────────────────

const BLANK_CONDITION = { field: 'object_type', op: 'eq', value: 'elephant' }

const BLANK_ACTION = {
  create_incident:        true,
  incident_severity:      'HIGH',
  notify_stakeholder_ids: [],
  actuate_sign_ids:       [],
  sign_state:             'CAUTION',
  message_template:       'Alert [{severity}]: {object_type} detected in {zone_name} by {device_name}. Confidence: {confidence}%. Incident: {incident_id}',
}

const BLANK = {
  name:         '',
  description:  '',
  use_case_id:  '',
  priority:     1,
  active:       true,
  conditions:   [{ ...BLANK_CONDITION }],
  confirmation: null,
  actions: {
    on_trigger: { ...BLANK_ACTION },
  },
}

// ── Field options ────────────────────────────────────────────────────────────

const CONDITION_FIELDS = [
  { value: 'object_type', label: 'Object Type',  ops: ['eq', 'neq', 'in'] },
  { value: 'confidence',  label: 'Confidence %', ops: ['gte', 'lte'] },
  { value: 'zone_id',     label: 'Zone ID',      ops: ['eq', 'neq', 'in'] },
  { value: 'device_id',   label: 'Device ID',    ops: ['eq', 'neq', 'in'] },
]

const OP_LABELS = { eq: '=', neq: '≠', gte: '≥', lte: '≤', in: 'in list', contains: 'contains' }
const SEVERITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
const SEV_COLORS = { LOW: 'text-sev-low', MEDIUM: 'text-sev-medium', HIGH: 'text-orange', CRITICAL: 'text-sev-critical' }

// ── Sub-components ───────────────────────────────────────────────────────────

function ConditionRow({ cond, onChange, onRemove, canRemove }) {
  const fieldDef = CONDITION_FIELDS.find(f => f.value === cond.field) || CONDITION_FIELDS[0]
  return (
    <div className="flex items-center gap-2">
      <Select value={cond.field} onChange={e => onChange({ ...cond, field: e.target.value, op: 'eq', value: '' })}
              className="flex-1">
        {CONDITION_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
      </Select>
      <Select value={cond.op} onChange={e => onChange({ ...cond, op: e.target.value })} className="w-24">
        {fieldDef.ops.map(op => <option key={op} value={op}>{OP_LABELS[op] || op}</option>)}
      </Select>
      <Input value={cond.value} onChange={e => onChange({ ...cond, value: e.target.value })}
             placeholder={cond.field === 'confidence' ? '70' : 'elephant'} className="flex-1" />
      {canRemove && (
        <button onClick={onRemove} className="text-ink-muted hover:text-sev-critical shrink-0">
          <Trash2 size={13} />
        </button>
      )}
    </div>
  )
}

function SectionHeader({ title, open, onToggle }) {
  return (
    <button onClick={onToggle}
            className="flex items-center justify-between w-full py-2 text-sm font-semibold text-ink text-left">
      {title}
      {open ? <ChevronUp size={14} className="text-ink-muted" /> : <ChevronDown size={14} className="text-ink-muted" />}
    </button>
  )
}

function ActionBlock({ label, action, onChange, stakeholders, roadSigns }) {
  function set(k, v) { onChange({ ...action, [k]: v }) }
  function toggleSH(id) {
    const ids = action.notify_stakeholder_ids || []
    set('notify_stakeholder_ids', ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id])
  }
  function toggleSign(id) {
    const ids = action.actuate_sign_ids || []
    set('actuate_sign_ids', ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id])
  }

  return (
    <div className="p-4 rounded-lg border border-line bg-surface space-y-4">
      <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide">{label}</div>

      <Field label="Incident Severity">
        <Select value={action.incident_severity} onChange={e => set('incident_severity', e.target.value)}>
          {SEVERITIES.map(s => (
            <option key={s} value={s} className={SEV_COLORS[s]}>{s}</option>
          ))}
        </Select>
      </Field>

      <Field label="Notify Stakeholders">
        <div className="space-y-1.5 mt-1">
          {stakeholders.length === 0 && (
            <p className="text-xs text-ink-muted">No stakeholders — add them in Stakeholder Registry.</p>
          )}
          {stakeholders.map(sh => (
            <label key={sh.id} className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox"
                     checked={(action.notify_stakeholder_ids || []).includes(sh.id)}
                     onChange={() => toggleSH(sh.id)}
                     className="rounded border-line accent-brand" />
              <span className="text-sm text-ink">{sh.name}</span>
              <span className="text-xs text-ink-muted">· {sh.role}</span>
            </label>
          ))}
        </div>
      </Field>

      {roadSigns.length > 0 && (
        <Field label="Actuate Road Signs">
          <div className="grid grid-cols-2 gap-1 mt-1">
            {roadSigns.map(rs => (
              <label key={rs.id} className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox"
                       checked={(action.actuate_sign_ids || []).includes(rs.id)}
                       onChange={() => toggleSign(rs.id)}
                       className="rounded border-line accent-brand" />
                <span className="text-xs text-ink">{rs.name}</span>
              </label>
            ))}
          </div>
          {(action.actuate_sign_ids || []).length > 0 && (
            <Field label="Sign State" hint="State applied to selected signs when this action fires">
              <Select value={action.sign_state || 'WARNING'} onChange={e => set('sign_state', e.target.value)}>
                <option value="WARNING">WARNING (red)</option>
                <option value="CAUTION">CAUTION (amber)</option>
                <option value="CLEAR">CLEAR (dark)</option>
              </Select>
            </Field>
          )}
        </Field>
      )}

      <Field label="Message Template" hint="Placeholders: {severity} {object_type} {zone_name} {device_name} {confidence} {incident_id}">
        <Textarea value={action.message_template || ''} onChange={e => set('message_template', e.target.value)} rows={3} />
      </Field>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function Rules() {
  const { data, loading, error, create, update, remove } = useApi('/api/rules')
  const { data: useCases }    = useApi('/api/use-cases')
  const { data: stakeholders } = useApi('/api/stakeholders')
  const { data: roadSigns }   = useApi('/api/road-signs')

  const [slideOpen, setSlideOpen]   = useState(false)
  const [editing, setEditing]       = useState(null)
  const [form, setForm]             = useState(BLANK)
  const [saving, setSaving]         = useState(false)
  const [saveError, setSaveError]   = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)
  const [showConfirmBlock, setShowConfirmBlock] = useState(false)
  const [showConfirmAction, setShowConfirmAction] = useState(false)
  const [openSections, setOpenSections] = useState({ cond: true, conf: true, actions: true })

  function openNew() {
    setEditing(null)
    setForm({ ...BLANK, conditions: [{ ...BLANK_CONDITION }], actions: { on_trigger: { ...BLANK_ACTION } } })
    setShowConfirmBlock(false)
    setShowConfirmAction(false)
    setSaveError(null)
    setSlideOpen(true)
  }

  function openEdit(rule) {
    setEditing(rule)
    const f = {
      ...rule,
      conditions: rule.conditions ? [...rule.conditions.map(c => ({ ...c }))] : [{ ...BLANK_CONDITION }],
      confirmation: rule.confirmation ? { ...rule.confirmation } : null,
      actions: {
        on_trigger: { ...BLANK_ACTION, ...(rule.actions?.on_trigger || {}) },
        ...(rule.actions?.on_confirm ? { on_confirm: { ...BLANK_ACTION, ...rule.actions.on_confirm } } : {}),
      },
    }
    setForm(f)
    setShowConfirmBlock(!!rule.confirmation)
    setShowConfirmAction(!!rule.actions?.on_confirm)
    setSaveError(null)
    setSlideOpen(true)
  }

  function close() { setSlideOpen(false) }
  function setF(k, v) { setForm(f => ({ ...f, [k]: v })) }
  function toggleSection(k) { setOpenSections(s => ({ ...s, [k]: !s[k] })) }

  function updateCondition(i, cond) {
    const next = [...form.conditions]
    next[i] = cond
    setF('conditions', next)
  }
  function addCondition() { setF('conditions', [...form.conditions, { ...BLANK_CONDITION }]) }
  function removeCondition(i) { setF('conditions', form.conditions.filter((_, j) => j !== i)) }

  function toggleConfirmation(enabled) {
    setShowConfirmBlock(enabled)
    if (enabled) {
      setF('confirmation', { required_count: 2, window_seconds: 900, same_zone: true })
    } else {
      setF('confirmation', null)
    }
  }

  function toggleOnConfirmAction(enabled) {
    setShowConfirmAction(enabled)
    if (enabled) {
      setForm(f => ({
        ...f,
        actions: { ...f.actions, on_confirm: { ...BLANK_ACTION, incident_severity: 'CRITICAL' } }
      }))
    } else {
      setForm(f => {
        const { on_confirm, ...rest } = f.actions
        return { ...f, actions: rest }
      })
    }
  }

  function setAction(key, block) {
    setForm(f => ({ ...f, actions: { ...f.actions, [key]: block } }))
  }

  function setConfirmField(k, v) {
    setF('confirmation', { ...form.confirmation, [k]: v })
  }

  async function save() {
    if (!form.name.trim())    { setSaveError('Rule name is required'); return }
    if (!form.use_case_id)    { setSaveError('Use Case is required'); return }
    if (!form.conditions?.length) { setSaveError('At least one condition is required'); return }
    setSaving(true); setSaveError(null)
    try {
      editing ? await update(editing.id, form) : await create(form)
      close()
    } catch (e) {
      setSaveError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const filteredSH = form.use_case_id
    ? stakeholders.filter(s => (s.use_case_ids || []).includes(form.use_case_id))
    : stakeholders

  const filteredSigns = form.use_case_id
    ? roadSigns.filter(rs => {
        const zone = rs.zone_id
        return true // signs belong to zones; show all for simplicity
      })
    : roadSigns

  const columns = [
    { key: 'name', label: 'Rule',
      render: row => (
        <div>
          <div className="font-medium text-ink">{row.name}</div>
          {row.description && <div className="text-xs text-ink-muted line-clamp-1">{row.description}</div>}
        </div>
      ),
    },
    { key: 'use_case_id', label: 'Use Case',
      render: row => {
        const uc = useCases.find(u => u.id === row.use_case_id)
        return uc
          ? <span className="text-xs font-medium" style={{ color: uc.color }}>{uc.name}</span>
          : <span className="text-xs text-ink-muted">{row.use_case_id || '—'}</span>
      },
    },
    { key: 'conditions', label: 'Conditions',
      render: row => (
        <div className="flex flex-wrap gap-1">
          {(row.conditions || []).map((c, i) => (
            <span key={i} className="text-xs bg-surface-alt border border-line rounded px-2 py-0.5 font-mono">
              {c.field} {OP_LABELS[c.op] || c.op} {c.value}
            </span>
          ))}
        </div>
      ),
    },
    { key: 'confirmation', label: 'Confirmation',
      render: row => row.confirmation
        ? <Badge color="amber">{row.confirmation.required_count}× in {row.confirmation.window_seconds / 60}m</Badge>
        : <Badge color="gray">Immediate</Badge>,
    },
    { key: 'priority', label: 'Priority',
      render: row => <span className="text-sm font-mono text-ink-muted">{row.priority}</span> },
    { key: 'active', label: 'Status',
      render: row => <Badge color={row.active ? 'green' : 'gray'}>{row.active ? 'Active' : 'Disabled'}</Badge> },
  ]

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHeader
        title="Rules Engine"
        description="Define when events trigger incidents and who gets notified. Higher priority rules are checked first."
        action={<Btn onClick={openNew}><Plus size={14} /> New Rule</Btn>}
      />

      <div className="flex-1 overflow-auto">
        {loading && <p className="px-6 py-4 text-sm text-ink-muted">Loading…</p>}
        {error   && <p className="px-6 py-4 text-sm text-sev-critical">{error}</p>}
        {!loading && (
          <Table columns={columns} rows={data} onEdit={openEdit} onDelete={setConfirmDel}
                 emptyMessage="No rules defined. Create a rule to make the engine respond to events." />
        )}
      </div>

      <SlideOver open={slideOpen} onClose={close} title={editing ? 'Edit Rule' : 'New Rule'}>
        <div className="space-y-5">
          <ErrorBanner error={saveError} />

          {/* Basic info */}
          <div className="space-y-4">
            <Field label="Rule Name" required>
              <Input value={form.name} onChange={e => setF('name', e.target.value)}
                     placeholder="e.g. Dual Confirmation – CRITICAL" />
            </Field>
            <Field label="Description">
              <Textarea value={form.description || ''} onChange={e => setF('description', e.target.value)}
                        placeholder="What does this rule detect and what does it do?" />
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Use Case" required>
                <Select value={form.use_case_id} onChange={e => setF('use_case_id', e.target.value)}>
                  <option value="">Select…</option>
                  {useCases.map(uc => <option key={uc.id} value={uc.id}>{uc.name}</option>)}
                </Select>
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Priority" hint="Higher = checked first">
                  <Input type="number" min="0" value={form.priority}
                         onChange={e => setF('priority', parseInt(e.target.value) || 0)} />
                </Field>
                <Field label="Status">
                  <Select value={form.active ? 'true' : 'false'}
                          onChange={e => setF('active', e.target.value === 'true')}>
                    <option value="true">Active</option>
                    <option value="false">Disabled</option>
                  </Select>
                </Field>
              </div>
            </div>
          </div>

          <div className="border-t border-line" />

          {/* Conditions */}
          <div>
            <SectionHeader title="Trigger Conditions" open={openSections.cond}
                           onToggle={() => toggleSection('cond')} />
            {openSections.cond && (
              <div className="space-y-2 mt-2">
                <p className="text-xs text-ink-muted mb-2">
                  All conditions must match (AND logic). The rule fires when an incoming event satisfies every condition.
                </p>
                {form.conditions.map((cond, i) => (
                  <ConditionRow key={i} cond={cond}
                                onChange={c => updateCondition(i, c)}
                                onRemove={() => removeCondition(i)}
                                canRemove={form.conditions.length > 1} />
                ))}
                <Btn variant="secondary" size="sm" onClick={addCondition}>
                  <Plus size={12} /> Add Condition
                </Btn>
              </div>
            )}
          </div>

          <div className="border-t border-line" />

          {/* Confirmation */}
          <div>
            <SectionHeader title="Confirmation (optional)" open={openSections.conf}
                           onToggle={() => toggleSection('conf')} />
            {openSections.conf && (
              <div className="mt-2 space-y-3">
                <p className="text-xs text-ink-muted">
                  Require multiple events before triggering — reduces false positives from a single camera.
                </p>
                <label className="flex items-center gap-2.5 cursor-pointer">
                  <input type="checkbox" checked={showConfirmBlock}
                         onChange={e => toggleConfirmation(e.target.checked)}
                         className="rounded border-line accent-brand" />
                  <span className="text-sm text-ink">Require confirmation from multiple events</span>
                </label>

                {showConfirmBlock && form.confirmation && (
                  <div className="p-4 rounded-lg border border-line bg-surface space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <Field label="Events required" hint="Min matching events to confirm">
                        <Input type="number" min="2" value={form.confirmation.required_count}
                               onChange={e => setConfirmField('required_count', parseInt(e.target.value) || 2)} />
                      </Field>
                      <Field label="Time window (seconds)" hint="All events within this window">
                        <Input type="number" min="60" value={form.confirmation.window_seconds}
                               onChange={e => setConfirmField('window_seconds', parseInt(e.target.value) || 900)} />
                      </Field>
                    </div>
                    <label className="flex items-center gap-2 cursor-pointer text-sm text-ink">
                      <input type="checkbox" checked={form.confirmation.same_zone}
                             onChange={e => setConfirmField('same_zone', e.target.checked)}
                             className="rounded border-line accent-brand" />
                      Events must be from the same zone
                    </label>
                    <div className="text-xs text-ink-muted bg-amber-50 border border-amber-100 rounded p-2 leading-relaxed">
                      Example: require 2 events within 15 min (900s) in the same zone before firing CRITICAL alert.
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="border-t border-line" />

          {/* Actions */}
          <div>
            <SectionHeader title="Actions" open={openSections.actions}
                           onToggle={() => toggleSection('actions')} />
            {openSections.actions && (
              <div className="mt-2 space-y-4">
                <div className="flex items-center gap-2 text-xs text-ink-muted mb-1">
                  <CheckCircle size={13} className="text-sev-low" />
                  <span>On Trigger — fires when conditions match</span>
                </div>
                <ActionBlock
                  label="On Trigger"
                  action={form.actions?.on_trigger || BLANK_ACTION}
                  onChange={block => setAction('on_trigger', block)}
                  stakeholders={filteredSH}
                  roadSigns={filteredSigns}
                />

                {showConfirmBlock && (
                  <>
                    <label className="flex items-center gap-2.5 cursor-pointer text-sm">
                      <input type="checkbox" checked={showConfirmAction}
                             onChange={e => toggleOnConfirmAction(e.target.checked)}
                             className="rounded border-line accent-brand" />
                      <span className="text-ink">Different actions when confirmed (optional)</span>
                    </label>

                    {showConfirmAction && (
                      <>
                        <div className="flex items-center gap-2 text-xs text-ink-muted">
                          <AlertTriangle size={13} className="text-sev-critical" />
                          <span>On Confirm — fires when confirmation threshold is met</span>
                        </div>
                        <ActionBlock
                          label="On Confirm (escalation)"
                          action={form.actions?.on_confirm || { ...BLANK_ACTION, incident_severity: 'CRITICAL' }}
                          onChange={block => setAction('on_confirm', block)}
                          stakeholders={filteredSH}
                          roadSigns={filteredSigns}
                        />
                      </>
                    )}
                  </>
                )}
              </div>
            )}
          </div>

          <SaveBar onSave={save} onCancel={close} saving={saving} />
        </div>
      </SlideOver>

      <ConfirmDialog
        open={!!confirmDel}
        message={`Delete rule "${confirmDel?.name}"? Events will no longer be evaluated against this rule.`}
        onConfirm={async () => { await remove(confirmDel.id); setConfirmDel(null) }}
        onCancel={() => setConfirmDel(null)}
      />
    </div>
  )
}
