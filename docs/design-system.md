# Design System — "Elevated Dialog"

A single, documented component + token layer so the UI is consistent and
professional rather than ad-hoc. **Live reference: open `/styleguide` in the app.**

## Principles

- **White base, Dialog red for chrome & primary actions, maroon top band.**
- **Severity uses a separate hue-spread scale** (critical→red, high→orange,
  medium→amber, low→green) so criticality never collides with brand chrome.
  Always paired with a label + icon (colour-blind safe).
- **Flat by default**; elevation (`shadow-card`) only on cards/drawers/modals.
- Light **surface canvas**, white cards — an "elevated" control-desk feel.

## Tokens — one source of truth

All design tokens live in [`tailwind.config.js`](../tailwind.config.js) and are
consumed as Tailwind classes (`bg-brand`, `text-ink-muted`, `bg-sev-critical`…).
[`src/theme/tokens.css`](../src/theme/tokens.css) mirrors them as CSS variables
**only** for non-Tailwind contexts (Leaflet div-icons, inline SVG fills).

Groups: `brand` · `maroon` · `orange` · `sev.{critical,high,medium,low}` ·
`state.{dispatched,delivered,failed}` · `hw.{on,off,offline,error,manual}` ·
`surface{,alt,sunken}` · `ink{,muted,subtle}` · `line{,strong}` · radius / shadow
/ z-index scales.

## Primitives — `src/components/ui/`

Import from the barrel: `import { Button, Card, Field } from '../components/ui'`.

| Module | Exports |
|---|---|
| `Button.jsx` | `Button`, `IconButton`, `Spinner` |
| `forms.jsx` | `Field`, `Input`, `Textarea`, `Select`, `Checkbox`, `Toggle`, `SegmentedControl` |
| `surfaces.jsx` | `Card`, `Panel`, `Section`, `PageHeader`, `EmptyState`, `Skeleton` |
| `status.jsx` | `Badge`, `SeverityChip`, `StatusBadge`, `StatusDot` |
| `Table.jsx` | `Table` (declarative columns + row actions) |
| `overlays.jsx` | `Drawer`, `Modal`, `ConfirmDialog` (Esc-to-close) |
| `Stepper.jsx`, `Tabs.jsx` | wizard stepper, underline tabs |
| `Toast.jsx`, `Banner.jsx` | `ToastStack`; `Banner`/`ErrorBanner`/`SaveBar` |

## Migration status

- **New screens** (Setup Wizard, Simulator, Style Guide) and the **ops screens**
  (Incidents/Map/Road Signs) use `ui/` directly.
- **Admin screens** still import from `components/admin/CrudShell.jsx`, which is now
  a thin **re-export shim** over `ui/` (so they inherit the system unchanged). The
  duplicate `ConfirmDialog`/`SeverityChip`/`StatusBadge`/`Toast` in `components/common/`
  are shims too. Deeper admin polish is a fast follow.

## Adding a primitive

1. Add it to the right module in `src/components/ui/`.
2. Export it from `src/components/ui/index.js`.
3. Add a demo block to `src/pages/StyleGuide.jsx` so `/styleguide` documents it.
