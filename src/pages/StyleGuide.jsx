import { useState } from 'react'
import { Palette, Camera, Bell, Plus, Trash2 } from 'lucide-react'
import {
  Button, IconButton, Field, Input, Textarea, Select, Checkbox, Toggle, SegmentedControl,
  Card, Panel, Section, PageHeader, EmptyState, Skeleton,
  Badge, SeverityChip, StatusBadge, StatusDot,
  Table, Drawer, Modal, ConfirmDialog, Stepper, Tabs, Banner,
} from '../components/ui'

const SWATCHES = [
  ['brand', 'bg-brand'], ['brand-hover', 'bg-brand-hover'], ['maroon', 'bg-maroon'], ['orange', 'bg-orange'],
  ['sev-critical', 'bg-sev-critical'], ['sev-high', 'bg-sev-high'], ['sev-medium', 'bg-sev-medium'], ['sev-low', 'bg-sev-low'],
  ['surface', 'bg-surface border border-line'], ['surface-alt', 'bg-surface-alt'], ['ink', 'bg-ink'], ['ink-muted', 'bg-ink-muted'],
]

export default function StyleGuide() {
  const [tab, setTab] = useState('a')
  const [seg, setSeg] = useState('grid')
  const [drawer, setDrawer] = useState(false)
  const [modal, setModal] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [toggle, setToggle] = useState(true)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHeader icon={Palette} title="Design System — Elevated Dialog"
        description="Living reference for every token and primitive. Import from components/ui." />

      <div className="flex-1 overflow-y-auto p-6 space-y-8 max-w-5xl">

        <Block title="Color tokens">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {SWATCHES.map(([name, cls]) => (
              <div key={name} className="text-xs">
                <div className={`h-12 rounded-lg ${cls}`} />
                <div className="mt-1 font-mono text-ink-muted">{name}</div>
              </div>
            ))}
          </div>
        </Block>

        <Block title="Buttons">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="danger">Danger</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="subtle">Subtle</Button>
            <Button variant="primary" loading>Loading</Button>
            <Button variant="primary" disabled>Disabled</Button>
            <IconButton icon={Plus} label="Add" variant="secondary" />
            <IconButton icon={Trash2} label="Delete" variant="ghost" />
          </div>
        </Block>

        <Block title="Severity & status">
          <div className="flex flex-wrap items-center gap-3">
            <SeverityChip severity="CRITICAL" pulse />
            <SeverityChip severity="HIGH" />
            <SeverityChip severity="MEDIUM" />
            <SeverityChip severity="LOW" />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status="ACTIVE" />
            <StatusBadge status="OPERATOR_REVIEW" />
            <StatusBadge status="RESOLVED" />
            <StatusBadge status="CLOSED" />
            <StatusBadge status="MANUAL_OVERRIDE" />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Badge color="gray">gray</Badge><Badge color="green">green</Badge>
            <Badge color="red">red</Badge><Badge color="amber">amber</Badge>
            <Badge color="brand">brand</Badge>
            <StatusDot online /><StatusDot online={false} />
          </div>
        </Block>

        <Block title="Forms">
          <div className="grid grid-cols-2 gap-4 max-w-xl">
            <Field label="Text input" hint="With a hint line"><Input placeholder="Type here…" /></Field>
            <Field label="Select"><Select><option>Option A</option><option>Option B</option></Select></Field>
            <Field label="With error" error="This field is required"><Input /></Field>
            <Field label="Textarea"><Textarea placeholder="Multi-line…" /></Field>
          </div>
          <div className="flex flex-wrap items-center gap-6">
            <Checkbox label="Checkbox option" checked readOnly />
            <Toggle checked={toggle} onChange={setToggle} label="Toggle setting" />
            <SegmentedControl options={[{ value: 'grid', label: 'Grid' }, { value: 'map', label: 'Map' }]} value={seg} onChange={setSeg} />
          </div>
        </Block>

        <Block title="Stepper & tabs">
          <Stepper steps={['Scenario', 'Sensors', 'Signs', 'Response', 'Review']} current={2} maxReached={3} onStepClick={() => {}} />
          <Tabs tabs={[{ value: 'a', label: 'Overview', count: 3 }, { value: 'b', label: 'Activity', icon: Bell }]} value={tab} onChange={setTab} />
        </Block>

        <Block title="Surfaces">
          <div className="grid grid-cols-3 gap-4">
            <Card><div className="font-medium text-ink">Card</div><p className="text-sm text-ink-muted mt-1">White, hairline border, soft shadow.</p></Card>
            <Panel title="Panel"><p className="text-sm text-ink-muted">Flat grouping for nested config.</p></Panel>
            <Card padded={false}><EmptyState icon={Camera} title="Empty state" description="Nothing here yet." /></Card>
          </div>
        </Block>

        <Block title="Banners">
          <div className="space-y-2">
            <Banner variant="info" title="Informational">Context for the operator.</Banner>
            <Banner variant="success">Saved successfully.</Banner>
            <Banner variant="warning" title="Heads up">Something needs attention.</Banner>
            <Banner variant="error" title="Error">Something went wrong.</Banner>
          </div>
        </Block>

        <Block title="Overlays">
          <div className="flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => setDrawer(true)}>Open drawer</Button>
            <Button variant="secondary" onClick={() => setModal(true)}>Open modal</Button>
            <Button variant="secondary" onClick={() => setConfirm(true)}>Confirm dialog</Button>
          </div>
        </Block>

        <Block title="Table">
          <Card padded={false}>
            <Table
              columns={[
                { key: 'name', label: 'Name' },
                { key: 'sev', label: 'Severity', render: r => <SeverityChip severity={r.sev} /> },
                { key: 'status', label: 'Status', render: r => <StatusBadge status={r.status} /> },
              ]}
              rows={[
                { id: 1, name: 'Sample row', sev: 'CRITICAL', status: 'ACTIVE' },
                { id: 2, name: 'Another row', sev: 'LOW', status: 'RESOLVED' },
              ]}
              onEdit={() => {}} onDelete={() => {}}
            />
          </Card>
        </Block>

        <Block title="Loading">
          <div className="space-y-2 max-w-md"><Skeleton className="h-6 w-1/3" /><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /></div>
        </Block>
      </div>

      <Drawer open={drawer} onClose={() => setDrawer(false)} title="Example drawer" description="Right-side slide-over"
        footer={<div className="flex justify-end gap-2"><Button variant="secondary" onClick={() => setDrawer(false)}>Cancel</Button><Button>Save</Button></div>}>
        <p className="text-sm text-ink-muted">Drawer body content. Press Esc or click the backdrop to close.</p>
      </Drawer>
      <Modal open={modal} onClose={() => setModal(false)} title="Example modal"
        footer={<><Button variant="secondary" onClick={() => setModal(false)}>Close</Button><Button>Confirm</Button></>}>
        <p className="text-sm text-ink-muted">Centred dialog content.</p>
      </Modal>
      <ConfirmDialog open={confirm} danger title="Delete item?" message="This action cannot be undone."
        confirmLabel="Delete" onConfirm={() => setConfirm(false)} onCancel={() => setConfirm(false)} />
    </div>
  )
}

function Block({ title, children }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-ink-muted uppercase tracking-wide">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  )
}
