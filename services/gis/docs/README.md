# Documentation

* [../ARCHITECTURE.md](../ARCHITECTURE.md): service boundary, components, data architecture, CRS
  conventions, security and the technology baseline.
* [security.md](security.md): access without credentials (the main platform owns sign-in), the tenant a
  request acts for, permissions, tenant isolation, sharing, the audit log, privacy, and the tests that
  prove them.
* [api/enrichment.md](api/enrichment.md): `POST /geo/v1/enrich`, the geo-context document, errors,
  authentication and settings.
* [api/spatial-queries.md](api/spatial-queries.md): the layer catalogue and features, within-distance,
  nearest, containment, reverse geocoding, event queries, the geofence, site and device-placement
  endpoints, exports, the audit log and `/me` - with the conventions (geometry, CRS, distances, paging,
  tenancy, permissions) and the error codes.
* [api/releases.md](api/releases.md): `GET /geo/v1/releases` - published reference data releases, the
  lineage and licence of every dataset, basemap artifacts and QA; attribution and licence-refused exports.
* [reference-data/pipeline.md](reference-data/pipeline.md): the reference data pipeline - running the
  application with the development sample, profiles, licences, coordinate operations, lineage, file and
  database QA, releases and the publish gate, the basemap, production datasets.
* [frontend/map-client.md](frontend/map-client.md): the map client - how to embed it, its components,
  how layers load, the spatial tools, the geofence editor, configuration and what is deliberately not
  there.
* [database/](database/README.md): the spatial data model (design rules), the generated schema
  reference and the ERD.
* [adr/](adr/): architecture decision records. Plan v0.9 decisions ADR-01 to ADR-11 remain in force
  unless an ADR here changes them.
* The project implementation plan (v0.9) is kept outside this repository, next to it in the project
  folder (`GIS_Core_Service_Implementation_Plan.docx`).

New decisions: copy `adr/TEMPLATE.md`, give it the next number, and link it from ARCHITECTURE.md
if it changes the boundary or a baseline choice.
