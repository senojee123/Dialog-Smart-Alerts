/**
 * CrudShell — back-compat shim.
 *
 * The shared admin primitives now live in the design system (src/components/ui).
 * This file re-exports them under their original names so existing admin pages
 * keep working unchanged while they migrate to importing from `../ui` directly.
 *
 * New code should import from `components/ui` instead. See /styleguide.
 */
import { Drawer, ConfirmDialog as UiConfirmDialog } from '../ui/overlays.jsx'

export { PageHeader, EmptyState, Card, Panel, Section } from '../ui/surfaces.jsx'
export { Button as Btn, IconButton } from '../ui/Button.jsx'
export { Badge, StatusDot, SeverityChip, StatusBadge } from '../ui/status.jsx'
export { Field, Input, Select, Textarea, Checkbox, Toggle, SegmentedControl } from '../ui/forms.jsx'
export { Table } from '../ui/Table.jsx'
export { ErrorBanner, SaveBar } from '../ui/Banner.jsx'

/** Old name for the right-side panel. */
export const SlideOver = Drawer

/** Old CrudShell ConfirmDialog was delete-only; preserve that default. */
export function ConfirmDialog({ title = 'Delete?', confirmLabel = 'Delete', danger = true, ...props }) {
  return <UiConfirmDialog title={title} confirmLabel={confirmLabel} danger={danger} {...props} />
}
