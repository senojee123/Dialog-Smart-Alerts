# The GIS map client

A reusable React map component for the spatial data the GIS Core Service exposes: events, devices,
geofences and reference layers, with the tools an operator needs to ask geographic questions of them -
what is within a distance, what is nearest, how far is this from that, what lies inside an area I drew.

The component is the product. `frontend/src/App.tsx` is a thin shell around it (a header, a status
panel), so that what an investigation or control-room application embeds is the same component this
repository runs and tests.

It shows **where things are**. What follows from any of that - who is told, what is dispatched, which
rule fires - belongs to the services that consume the GIS service's answers, not here and not in the
service ([ADR-0012](../adr/ADR-0012-gis-only-service-boundary.md)). A test asserts it: `boundary.test.ts`
reads the client's own source and fails if it starts speaking of notifications, recipients or channels.

## Embedding it

In the main platform (Dialog Smart Alerts, React 18) the map is shown as a same-site embedded page: the
platform's backend serves the built map application at `/gis-app/` and its `/gis` page shows it in a
frame, where the map leaves out its own header (see [../integration.md](../integration.md)). A React 19 host can instead import the component:

```tsx
import { MapContainer } from 'gis-core-service-web/map/MapContainer';
import { createGisApi } from 'gis-core-service-web/services/gisApi';

const api = createGisApi({
  baseUrl: '/api/gis',                           // where the service is reachable (the platform's proxy)
  tenantId: null,                                // null: the platform's organisation (GIS_TENANT_ID)
});

<MapContainer
  api={api}
  tenantId="wildlife-dept"
  panels={['layers', 'legend']}                  // the host provides the rest of the UI
  deviceState={(deviceId) => health.stateOf(deviceId)}
  onSelectionChange={(selection) => { investigation.focus(selection); }}
/>;
```

| Prop | Meaning |
|---|---|
| `api` | The `GisApi` to read through. The default is built from `VITE_*` (see below); a host passes its own, which is also what makes the component testable and re-targetable. |
| `tenantId` | Tenant whose operational data to show (default: `VITE_TENANT_ID`, else the platform's organisation). |
| `basemaps`, `initialBasemapId` | Basemaps the operator can switch between; the neutral background is always available. |
| `initialVisibleLayers` | Which layers start on; the default comes from the layer table. |
| `initialView` | `{ zoom, latitude, longitude }` to open at instead of Sri Lanka; the map then does not re-frame itself to the service area. The reference application reads it from a linkable view in the URL, `#map=<zoom>/<lat>/<lon>` (`parseViewHash`, which refuses anything out of range). |
| `panels` | Which side panels to render: `layers`, `events`, `tools`, `editor`, `export`, `legend`. `[]` renders the map alone and leaves the UI to the host. A panel the caller's permissions do not allow is not rendered even when asked for (see Configuration). |
| `deviceState` | `(deviceId) => 'online' \| 'degraded' \| 'offline' \| undefined`. See *Device state* below. |
| `featureLimit`, `maxFeaturePages` | How much of a layer to read per window. |
| `eventWindowHours`, `eventRefreshIntervalMs` | The event window to start with, and how often to re-read it (`0`: on request only). |
| `onSelectionChange`, `onViewportChange` | What the operator selected, and where the map is looking. |

Nothing is registered on `window` and no state is global, so several maps can be mounted at once.

## The component tree

```text
MapContainer                 the map, the viewport, the selection; owns the panels a host asks for
├── LayerManager             mounts one component per visible layer; each owns its own request
│   ├── EventLayer           clustered event points, plus a source for event lines and areas
│   ├── DeviceLayer          devices coloured by reported state, their labels
│   │   ├── FieldOfViewLayer what each device observes
│   │   └── SiteLayer        installation sites
│   ├── GeofenceLayer        the tenant's geofences, by status
│   └── ReferenceLayer       administrative areas, protected areas, risk zones, water, roads,
│                           settlements, facilities
├── OverlayLayer            the ruler, the search circle, query results, the drawn filter area,
│                           the geofence being edited
├── FeaturePopup            what was selected, and where it is (geographic context)
├── MapStatus               loading, failures, truncation, the reference data release in use
└── panels
    ├── MapControls         layer visibility by group, basemap, labels, reload
    ├── Legend              what the colours mean, for the layers that are on
    ├── EventFilters        type, source and the time window
    ├── SpatialTools        radius search, nearby devices, ruler, draw-to-filter
    ├── GeofenceEditor      draw, adjust, validate and save a geofence
    └── ExportPanel         a layer in the current view, or the events of the window, as a GeoJSON file
```

Supporting modules: `map/layers/layerCatalogue.ts` (the layer table), `map/access.ts` (what the caller's
permissions let the map offer), `map/state/*` (loading and selection state), `map/tools/*`,
`map/editor/*`, `map/popup/*`, `geo/*` (projection and geometry),
`services/*` (the API boundary), `types/api.ts` (the contracts, validated with zod).

## Layers

`map/layers/layerCatalogue.ts` is the client's side of the service's catalogue: for each layer it says
what to call it, which group it belongs to, from which zoom it is worth loading, what its legend says,
and what to ask for at the current zoom. The service's own catalogue (`GET /geo/v1/layers`) is the
authority on what exists: a layer the deployment does not publish is dropped when the catalogue arrives,
so the map never asks for something that is not there.

| Layer | Source | From zoom | Notes |
|---|---|---|---|
| Events | `GET /geo/v1/events` | 0 | clustered; bounded in time as well as in space |
| Devices | `ops.device` | 8 | coloured by the state a host supplies |
| Fields of view | `ops.device_field_of_view` | 10 | modelled or surveyed, as recorded |
| Sites | `ops.site` | 9 | off by default |
| Geofences | `ops.geofence` | 0 | active solid, draft and suspended dashed; archived ones are not drawn |
| Administrative areas | `ref.admin_area` | 0 | level follows the zoom: 1, 2, 3, then 4 |
| Protected areas | `ref.protected_area` | 6 | |
| Risk zones | `ref.risk_zone` | 6 | shaded by severity; off by default |
| Water | `ref.water_body` | 8 | |
| Roads | `ref.road` | 9 | width and colour by class |
| Settlements | `ref.settlement` | 7 | footprints where the release has them |
| Facilities | `ref.facility` | 10 | off by default |

**How a layer loads.** Panning a map produces a viewport change per frame, so the client asks the API
for a *window*: a padded box around the viewport, replaced only when the viewport leaves it or the zoom
crosses an integer (`useBoundsWindow`). For that window the layer follows the service's keyset cursor for
a bounded number of pages (`featureLimit` × `maxFeaturePages`), and says plainly when it stopped - the
status line reads "showing the first pages only" rather than quietly drawing part of an answer. What was
loaded stays on the map while the next window is in flight, so the map does not flicker; a layer that is
switched off is unmounted, which is also what stops it being requested.

Requests are clipped to the service area, because the API refuses a bounding box that does not overlap
it - and no layer is requested until the service area is known, so the first request is already the right
size. A drawn filter area narrows the box as well (see *Spatial tools*).

## Events

Event points are clustered by MapLibre; a click on a cluster zooms into it, a click on an event selects
it. Events whose geometry is not a point - a track, a sighting area - are drawn in a second, unclustered
source.

The window is bounded because the service bounds it: event storage is partitioned by month, and a window
longer than 31 days is refused. The panel offers 1 h, 6 h, 24 h, 7 d and 31 d, or a pinned start and end,
and it shows the window **the service answered for**, so an operator is never reading a different span
than they think.

Selecting an event shows its own attributes, the administrative codes its geo-context recorded, and - 
resolved through `GET /geo/v1/reverse` - the names of the areas it lies in, the nearest settlement and the
nearest road with their distances. For an event this is loaded straight away; for anything else the popup
offers to resolve the position.

## Device state

The GIS service records **where a device is**, not whether it is working. The map therefore takes a
`deviceState` function from the host application - typically backed by a device-management or telemetry
service - and colours each device by what it answers: online, degraded, offline, or *not reported* when
it answers nothing. A device with no report is never drawn as healthy, and this client collects no
health data of its own.

The device's GIS lifecycle status (`planned`, `active`, `inactive`, `decommissioned`) is a different
thing, and is shown in the popup as an attribute of the placement.

## Spatial tools

| Tool | What it does |
|---|---|
| Radius search | Click a position; `POST /geo/v1/query/within-distance` against the layer chosen, with the circle drawn. The layers offered are the ones the service says can answer that query. |
| Nearby devices | Click a position; `POST /geo/v1/query/nearest` against `ops.device`, bounded as the API requires. Not paged. |
| Measure | Click along a path; the running and total distance in **metres on the EPSG:5235 plane**, the same quantity the API reports. |
| Draw to filter | Draw an area; the map then shows only what lies inside it. Requests still narrow by bounding box server-side, and the exact test is done on the drawn polygon in the client. |

Results are listed with their distances and can be clicked to move the map to them. Changing the distance
or the target layer after a search does not silently re-run it: the panel says the results are the previous
search and offers *Search again*, so what is listed always matches what was asked.

### Distances and the EPSG:5235 plane

The API answers every distance in metres on the SLD99 / Sri Lanka Grid 1999 plane
([ADR-02](../../ARCHITECTURE.md#7-coordinate-reference-systems-adr-02)). The client measures the same
way: `geo/sld99.ts` carries the transformation PROJ uses for EPSG:4326 → EPSG:5235 (WGS84 geodetic →
geocentric → the inverse of the published "SLD99 to WGS 84 (1)" Helmert transformation → Everest 1830
geodetic → Transverse Mercator). So a radius the operator draws, the ruler, and the `distanceM` of a
query answer are one quantity rather than three.

That implementation is held to PROJ's own numbers: `python -m app.tools.export_crs_reference` writes
`frontend/src/geo/sld99Reference.generated.ts` from the EPSG definition, and `sld99.test.ts` checks the
client against it in both directions. The agreement is within **2 mm** forward and **5 mm** round trip,
far below the 0.01 m the API rounds to. Re-run the exporter (and commit the fixture) if PROJ is upgraded.

## The geofence editor

Terra Draw is the input device; the **definition** is what the editor keeps and what the service stores:

| Shape | Definition | Drawn as |
|---|---|---|
| Polygon | the polygon | a Terra Draw polygon, kept editable (drag corners, add and remove them) |
| Circle | a centre and a radius in metres | drawn as a ring, then measured: the centre is recovered exactly (the ring is a Web Mercator circle, so its centre is the mean of its positions in that projection) and the radius is offered as a number to adjust |
| Corridor | a centre line and a half-width in metres | a Terra Draw line, kept editable; the swept area is drawn as a round-capped line whose width *is* the half-width in metres |

A polygon is drawn by clicking its corners and clicking the first one again; a corridor by clicking along
its centre line and double-clicking the last point; a circle with two clicks, the centre and then a point
on the radius. The click that finishes a drawing is not taken as a selection, so it does not open the
popup of whatever lies under it.

Terra Draw reports every feature it changes, including its own guidance features: the corner handles it
adds to a selected shape and removes when the shape is deselected, and the shape being drawn before it is
finished. The editor takes only the changes of the shape it holds, so deselecting keeps the edited shape
and a drawing discarded with Escape never becomes the draft. Switching the basemap replaces the map's
style, which removes Terra Draw's sources; the map then starts a new Terra Draw instance on the new style
and the editor hands it the draft as it stands (a drawing in progress is lost).

A circle is not stored as its drawn ring, because the service tests circle hits against the centre and
the radius. The map draws the exact circle from the definition (`circlePolygon`, generated on the
EPSG:5235 plane), so what the operator sees is what the service will store.

Before sending, the draft is checked against the same rules the service applies: a name, a geometrically
valid shape that does not cross itself, positions inside the service area, a radius within 50 km (5 km
for a corridor half-width), tenants named only with the `shared` policy, and a period that ends after it
starts. These checks are a courtesy, not the authority - every request is validated by the service, and
when it refuses one, its problem detail and code are shown as they came back (a `409 version_conflict`
says which version the geofence is now at).

Saving creates (`POST`) or replaces (`PUT`, stating the version that was read). A replace is a full
replace, so the editor carries everything it read - including the `attributes` the author set, which it
does not interpret. `DELETE` archives, and *Delete permanently* purges, because stored geo-context hits
name geofences and their versions.

There is one Terra Draw instance per map, because two would fight over the pointer; what a drawing is
*for* travels with it as its purpose, so the editor and draw-to-filter share it.

## Configuration

Read once at start-up from Vite's environment (`frontend/src/config.ts`). None of it is a secret.

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | Where the service is; the dev server proxies `/api` to FastAPI. |
| `VITE_BASEMAP_STYLE_URL` | - | A MapLibre style URL, e.g. `/basemap/ref-2026.09-dev/style.json` (the pipeline's basemap). Without one, the map draws a neutral background. |
| `VITE_BASEMAPS` | - | A JSON array `[{"id","label","styleUrl"}]` for several basemaps. |
| `VITE_TENANT_ID` | - | Tenant to read operational data for, sent as `X-GIS-Tenant-Id`; empty: the platform's organisation (`GIS_TENANT_ID`). |
| `VITE_FEATURE_LIMIT` | 500 | Features per page. |
| `VITE_MAX_FEATURE_PAGES` | 4 | Pages to follow per layer per window. |
| `VITE_EVENT_WINDOW_HOURS` | 24 | The event window to start with (at most 31 days). |
| `VITE_EVENT_REFRESH_INTERVAL_MS` | 0 | Re-read events on this interval; `0` leaves it to the operator. |
| `VITE_HEALTH_POLL_INTERVAL_MS` | 15000 | How often the status panel re-checks readiness. |

The client sends no credentials: the main platform owns sign-in. It reads `GET /geo/v1/me` and offers
only what the caller's permissions allow (today every request has them all): the geofence editor
needs `geofences:write`, the event layer and filters `events:read`, radius search and nearby devices
`query:spatial` (measuring and draw-to-filter work in the browser and are always there), and the export
panel `data:export`. Until the answer arrives - or if it cannot be had - the map reads (the API decides) and
offers nothing that changes or exports data. The API checks every request regardless
([../security.md](../security.md)).

### Basemap and attribution

The reference data pipeline builds the basemap of a release into `data/basemap/<release>/`: a PMTiles
file, a MapLibre style whose source is `pmtiles:///basemap/<release>/<name>.pmtiles`, and Noto Sans
glyphs ([../reference-data/pipeline.md](../reference-data/pipeline.md#8-basemap)). The client registers
the `pmtiles://` protocol, so the tiles are read with HTTP range requests from static files; the dev and
preview servers serve `data/basemap` at `/basemap` (`GIS_BASEMAP_DIR` to change it), production serves it
from the ingress or CDN at the same path. The client's own labels use `Noto Sans Regular`
(`LABEL_FONT` in `map/mapStyle.ts`), so a basemap used with the client must provide that font.

The attribution the reference data's licences require arrives with the layer catalogue (`attribution`)
and is shown in the map's attribution control, next to the basemap's own. Layers the catalogue marks
`exportable: false` (a source that does not allow redistribution) are not offered in the export panel,
and an export shows the attribution to keep with the file.

## Tests

`npm test` runs the suite in jsdom. There is no WebGL there, so the map library is mocked
(`src/test/reactMapGl.tsx`) and the components' own behaviour is what is tested: which layers are
requested for a window, that a source is clustered, which layers a click may select from, what a
selection shows, what the editor sends. The rest is pure logic and is tested directly: the projection
against PROJ's numbers, the geometry helpers, the layer table, the request planner, the draft validator,
the query builders, and the API boundary against a recorded `fetch`.

Doubles live in `src/test/`: `apiStub` (the `GisApi`), `fetchStub` (the transport), `drawStub` (the Terra
Draw controller), and the fixtures, whose shapes mirror the backend's response models.

## What is deliberately not here

* No alert centre, no notification UI, no recipient or subscription concepts - see the boundary test.
* No aggregation (counts per area, heatmaps) and no vector tiles yet: layers are read by viewport and
  paged, which is why the heavier layers have a minimum zoom.
* No offline cache: the client holds the current window, nothing more.
* An event that is inside a cluster cannot be highlighted while it is clustered; zooming in separates it.
* No device health collection; the seam for it is the `deviceState` prop.
