# Geodata

| Folder | Content | In git? |
|---|---|---|
| `pipeline/profiles/` | Pipeline profiles: `dev.toml` (open data), `production.example.toml` (agency data template) | Yes |
| `pipeline/placeholders/` | Labelled development placeholders for layers with no open source (risk zones) | Yes |
| `raw/` | Original files exactly as received (OSM extract, geoBoundaries, agency deliveries), each with a `.provenance.json` | No |
| `processed/` | Release directories built by the pipeline (`processed/<release>/`) | No |
| `basemap/` | Basemaps built by the pipeline (`basemap/<release>/`: PMTiles, style, glyphs); served at `/basemap` | No (large; delivered or rebuilt) |
| `sample/` | The development sample: release `ref-2026.09-dev` and a tenant's operational objects ([README](sample/README.md)) | Yes |
| `fixtures/` | Small reference data for automated tests ([README](fixtures/README.md)) | Yes |

How data gets from `raw/` to PostGIS, and what is recorded and checked on the way:
[docs/reference-data/pipeline.md](../docs/reference-data/pipeline.md).

Rules:

* **Licences are stated, never assumed.** Every source in a profile states its licence, attribution,
  whether commercial use and redistribution are allowed, share-alike and any written permission; a
  production profile needs an approved licence review for each. The pipeline and the database QA refuse
  restricted licences without permission.
* **Do not use WDPA** protected-area data without written permission from UNEP-WCMC; the development
  sample uses OpenStreetMap, production uses DWC and Forest Department boundaries under agreement.
* OpenStreetMap data is ODbL: attribute it wherever it is shown (the map and the API do) and offer
  derived databases shared outside the platform under the same licence.
* Everything is stored in WGS 84 (EPSG:4326). SLD99 (EPSG:5235) and Kandawala (EPSG:5234) sources are
  transformed with the operation PROJ rates most accurate, verified with ogr2ogr and pyproj and, when the
  profile has them, control points; the operation and its accuracy are recorded with the data.
* Placeholders are labelled `DEV PLACEHOLDER`, marked synthetic, and cannot reach a production release.
* Never commit tenant data or personal data. The sample tenant's objects are invented and labelled `DEV`.
