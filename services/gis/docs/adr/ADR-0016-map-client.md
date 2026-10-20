# ADR-0016: The map client

* Status: accepted
* Date: 2026-09-22
* Refines: plan §8 (map client); ADR-0012 (service boundary), ADR-02 (coordinate systems), ADR-07
  (MapLibre v6), ADR-0015 (spatial query API)

## Context

The platform needs a map that shows what the GIS service knows, and that a larger
investigation or control-room application can embed rather than reimplement. Findings while building it:

* A map client is where "just add a button" pressure lands. A geofence editor is one short step from a
  "notify everyone inside this area" button, which would put recipients and messaging in the GIS
  platform - the boundary ADR-0012 draws.
* Panning a map produces a viewport change per animation frame. Asking the API per frame is absurd, and
  asking once per pan is still too often.
* The service measures distances on the EPSG:5235 plane. A client that measures differently would show an
  operator a radius that does not mean what the API's `distanceM` means.
* Terra Draw draws a circle as a ring of positions. The service stores a circle as a centre and a radius
  and tests hits against *those*, so a stored ring would be a different geofence from the one drawn.
* Two drawing instances on one map fight over the pointer.
* The device layer needs to show whether a device is working, and the GIS service does not know: it
  records where a device is.
* React's current lint rules refuse `setState` in an effect body and refs written during render, which
  rules out the usual "loading flag" and "latest value" patterns.

## Decision

1. **One embeddable component, everything injected.** `MapContainer` takes the API client, the tenant,
   which panels to render (`panels={[]}` renders the map alone) and how to find out a device's state. It
   keeps no global state and registers nothing on `window`, so a host can mount it more than once, drive
   it from its own UI, and point it at its own gateway. The reference application around it is a header
   and a status panel.
2. **No notification surface, asserted.** `boundary.test.ts` reads the client's own source and fails on
   "notification", "notify", "recipient", "subscriber", "alert centre" or a channel name, and checks that
   every path the client calls is one of the service's geographic endpoints. The API has the equivalent
   test over its OpenAPI document (ADR-0015).
3. **A client layer table, the service's catalogue as the authority.** `layerCatalogue.ts` says how each
   layer is drawn, from which zoom, and what to ask for at the current zoom; `GET /geo/v1/layers` says
   what exists, and a layer the deployment does not publish is dropped. Adding a layer to the map is an
   entry in that table.
4. **Window-based loading, bounded and honest.** A padded box around the viewport is the request, replaced
   only when the viewport leaves it or the zoom crosses an integer. Each layer follows the service's
   keyset cursor for a bounded number of pages and reports when it stopped, so "part of the answer" is
   never drawn as if it were all of it. Previous features stay visible while the next window loads.
5. **Loading is derived, not stored.** Each layer's state is the answer plus the identity of the request
   it belongs to; "loading" is an answer that does not belong to the current request. No effect sets
   state to say it is loading, which is what the React rules ask for and also removes a class of stale-
   answer bugs.
6. **The client measures in EPSG:5235, checked against PROJ.** `geo/sld99.ts` implements the pipeline
   PROJ uses (Helmert to the SLD99 datum, then Transverse Mercator on Everest 1830), so the ruler, a
   drawn radius and the API's `distanceM` are one quantity. `app.tools.export_crs_reference` exports
   PROJ's own values and a test holds the implementation to them: within 2 mm forward, 5 mm round trip.
7. **The geofence definition is the truth; Terra Draw is an input device.** A drawn circle is measured
   back into a centre and a radius (the centre exactly, from the Web Mercator ring Terra Draw produced),
   and the map then draws the exact circle from the definition. A polygon and a corridor centre line stay
   in Terra Draw so their vertices remain editable; a corridor's swept area is drawn as a round-capped
   line whose width *is* the half-width in metres.
8. **One Terra Draw instance, with a purpose.** The editor and draw-to-filter share it; what a drawing is
   for travels with it, and the container routes finished shapes accordingly.
9. **Device state comes from the host.** `deviceState` is a function the embedding application supplies;
   a device with no report is drawn as "not reported", never as healthy. The client collects no health
   data, which keeps the GIS service's boundary intact on the screen as well as in the API.
10. **Geometry is read-only and validated at the boundary.** The API contracts are zod schemas whose
    geometry is deeply read-only, so nothing can rewrite coordinates in place, and a feature MapLibre
    hands back from a click is parsed rather than asserted. One documented conversion hands read-only data
    to MapLibre's mutable types.
11. **Draw-to-filter narrows twice.** The drawn area's bounding box narrows the request server-side; the
    exact containment test runs in the client on the drawn polygon. Containment as a *question* about the
    data belongs to the API (`POST /geo/v1/query/contains`); this is only about what is drawn.

## Consequences

* The heavier reference layers have a minimum zoom, so a country-scale view shows administrative areas
  and protected areas but not roads or facilities. Tiles (C5) are what will remove that limit.
* Because the request identity includes the filters and the window but not the zoom, zooming inside a
  window does not refetch - except for administrative areas, whose level is a function of zoom by design.
* An operator can pin an event window, and the panel shows the window the service answered for; a
  relative window is resolved when the request is made, so paging through it cannot drift.
* Mocking the map library is what makes the components testable in jsdom; the mock records sources,
  layers and the map's props, so tests assert on what would be drawn rather than on pixels.
* The client carries its own copy of a PROJ transformation. If PROJ's answer for EPSG:5235 changes, the
  exporter must be re-run and the fixture committed - the test will say so.
* Terra Draw is in its own bundle chunk: it is needed only once an operator draws something.
* `VITE_API_ACCESS_TOKEN` exists for local development against a development-signed token. A deployment
  passes a token provider instead, and the variable stays unset.
* Colouring a device, site or geofence by its lifecycle status needs that status in the answer, not only as
  a filter, so the layer registry now exposes `status` as a property of `ops.site`, `ops.device` and
  `ops.geofence` (a unit test asserts it stays that way). A client cannot paint what the API does not
  return, and a `match` expression on a missing property fails silently - which is how this was found.
