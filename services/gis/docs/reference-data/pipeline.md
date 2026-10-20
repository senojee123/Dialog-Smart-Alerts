# Reference data pipeline

How Sri Lankan reference data gets from its source to PostGIS: acquired, transformed to WGS 84, checked,
loaded into a **release**, checked again in the database, and published. The same steps build the basemap.
Decisions and alternatives are in [ADR-0018](../adr/ADR-0018-reference-data-pipeline.md).

```
profile (TOML) ─► fetch ─► build ─────────────► load ──────────► QA ─────────► publish ─► current
  sources          raw/     ogr2ogr, GeoPandas,   draft release    database       gate:       one per
  licences         + prove- Shapely, pyproj       (PostGIS,        checks         fresh QA,   database
  datasets         nance    file QA per dataset   ST_MakeValid     (ST_IsValid,   no open
                            processed/<release>/  repairs logged)  topology ...)  errors,
                            basemap/<release>/                                    licences
```

| Step | Command (from `backend/`) | Needs |
|---|---|---|
| List sources and licences | `python -m app.pipeline sources --profile P` | pipeline extra |
| Acquire files | `python -m app.pipeline fetch --profile P` | pipeline extra |
| Build a release directory | `python -m app.pipeline build --profile P [--release C]` | pipeline extra, GDAL ≥ 3.8 |
| Build the basemap | `python -m app.pipeline basemap --profile P --release C` | pipeline extra, GDAL ≥ 3.8 |
| Load, check, publish | `python -m app.pipeline load DIR [--basemap B] [--publish\|--current]` | migration login only |
| All of the above | `python -m app.pipeline run --profile P --basemap [--publish\|--current]` | all |
| QA again, waive, publish | `qa C`, `waive C FINDING --reason T`, `publish C [--current]` | migration login |
| Inspect | `status [C]`, `diff C [--against R]` | migration login |
| Current, retire | `current C`, `retire C` | migration login |

Every command prints JSON; logs go to stderr. Changes to releases are written to the audit log with
`--actor` (default: the OS login) and channel `loader`.

**Tooling.** GDAL/ogr2ogr reads and reprojects every source and writes the tiles; GeoPandas and Shapely
map, clean and check features; pyproj chooses and verifies coordinate operations. They are the
`pipeline` extra (`pip install -e '.[pipeline]'`, locked in `backend/requirements-pipeline.lock`) plus
`gdal-bin`; the `pipeline` Docker target has both. Loading and QA need neither: the API image can load a
built release.

## 1. Running the application locally with the sample

The repository carries a built development release, so the whole application runs without GDAL or
downloads:

| Path | What | Size |
|---|---|---|
| `data/sample/ref-2026.09-dev/` | Release `ref-2026.09-dev`: 17 datasets, 37 235 features (`manifest.json`, `*.geojson.gz`, `qa/`, `SOURCES.md`, `build.json`) | 11 MB |
| `data/sample/operational/wildlife-dept.json` | A development tenant's sites, devices, geofences and a batch of events near Habarana | 12 KB |
| `data/basemap/ref-2026.09-dev/` | Basemap: `lka.pmtiles` (z0-14), `style.json`, Noto Sans glyphs, `artifacts.json` | 22 MB |

```bash
cp .env.example .env                                   # replace the CHANGE_ME values
docker compose up --build -d                           # db -> migrate -> api -> web
docker compose --profile sample run --rm sample-data   # load the release + basemap, seed the tenant
```

`sample-data` runs [`docker/dev-sample.sh`](../../docker/dev-sample.sh): it loads the release (with the
basemap as its artifacts, when `data/basemap/ref-2026.09-dev` exists), runs the database QA, makes it
current, then runs `python -m app.tools.seed_dev_data`, which registers the tenant `wildlife-dept` and
creates its 5 sites, 6 devices (with fields of view) and 3 geofences through the same service the API
uses, and enriches 10 events through the geo-context engine. Running it again changes nothing except
adding a new batch of events for the last 24 hours (so the map's default event window has something to
show). It refuses `GIS_ENV=production` and a current release that is not a development or test release.

Then open the map with `VITE_TENANT_ID=wildlife-dept` (README, *Opening the map on real data*). The map client shows the basemap from `/basemap/ref-2026.09-dev/style.json` (the default of
`VITE_BASEMAP_STYLE_URL` in `.env.example`), the reference layers, the tenant's objects and events, and
the attribution the licences require.

Without Docker, the same from `backend/` with the `GIS_DB_*` settings of both logins:

```bash
python -m app.pipeline load ../data/sample/ref-2026.09-dev --basemap ../data/basemap/ref-2026.09-dev --current
python -m app.tools.seed_dev_data ../data/sample/operational/wildlife-dept.json
```

The Vite dev server serves `data/basemap` at `/basemap` (`GIS_BASEMAP_DIR` to point elsewhere), with the
HTTP range requests PMTiles needs; production serves the directory from the ingress or CDN at the same
path.

## 2. Profiles

A profile (`data/pipeline/profiles/*.toml`) declares everything the pipeline uses; nothing is inferred.

* `dev.toml` builds the development release (open data only).
* `production.example.toml` is the template for a production profile. As shipped **it refuses to build**:
  its agency sources have placeholder licences, no commercial use and no review, and a production
  profile needs an approved review for every source.

```toml
[profile]
name = "dev"
purpose = "development"            # production | development | test
release = "ref-{year}.{month}-dev" # release code template
description = "..."

[areas]                             # named WGS 84 boxes: dataset areas and QA extents
national = [79.44, 5.66, 82.15, 10.08]
pilot = [80.45, 7.75, 81.10, 8.30]

[sources.<code>]                    # one per original file
name, publisher, url
licence = "ODbL-1.0"                # SPDX where one exists; stated, never assumed
licence_url, attribution
commercial_use_allowed, redistribution_allowed, share_alike
permission_reference                # the licensor's written permission, when the licence needs one
review = { status = "approved", reviewed_by = "...", reviewed_on = 2026-09-01, reference = "..." }
file = "osm/sri-lanka-latest.osm.pbf"   # under the raw directory (or base = "profile")
download = "https://..."            # optional; or download_env / auth_header_env (environment variables)
sha256 = "..."                      # optional; enforced
version = "..." | version_from = "osm_replication_timestamp"
source_crs = "EPSG:5235"            # required when the file does not state its CRS; checked when it does
coordinate_operation = "..."        # optional: pin an operation (part of its name, or a PROJ pipeline)
control_points = [...]              # optional: surveyed points the transformation must hit
geometry_source = "survey"          # survey | gps | digitised | imagery | osm | derived | synthetic | unknown

[[datasets]]                        # one per output file
name = "roads-national"
layer = "ref.road"                  # which reference table
source = "osm-geofabrik-lka"
adapter = "osm"                     # vector | osm | placeholder
theme = "roads"                     # osm: settlements, facilities, roads, water_lines, water_areas, protected_areas
area = "national"                   # features outside are left out
accuracy_m = 20                     # nominal horizontal accuracy (required)
qa = { expected_area = "national", min_features = 5000, min_coverage_ratio = 0.8 }

[basemap]
osm_source, land_source, glyphs_source, detail_area, min_zoom, max_zoom, public_path
```

**Keeping production sources configurable.** Everything that differs by deployment is in the profile or
the environment: which file each layer comes from, its field mapping (`id_field`, `fields`, `values`,
`input_layer`, `where`), its CRS and control points, its licence and review, download URLs
(`download_env`) and credentials (`auth_header_env`). Profiles are data; the code has no source names in
it. Credentials are never written to a profile.

### Adapters

| Adapter | Reads | Use |
|---|---|---|
| `vector` | Any GDAL vector source (GeoPackage, Shapefile, FileGDB, GeoJSON, zipped) | Agency deliveries, geoBoundaries. Fields are mapped by the profile. |
| `osm` | An OpenStreetMap PBF extract, staged once per build with three ogr2ogr passes (`osmconf.ini`) | Settlements, facilities, roads, rivers, water bodies, protected areas |
| `placeholder` | A GeoJSON of labelled placeholders | Development only (risk zones). Every feature must be named `DEV PLACEHOLDER ...` and marked `placeholder: true`. Refused in production. |

OpenStreetMap tag rules (`app/pipeline/adapters/osm.py`), for example: road class from the route number
(`ref=A6` → `A`) before the highway type; irrigation tanks recognised by name (`wewa`, `kulam`, `tank`);
protected areas only with a recognised designation (national park, sanctuary, nature/forest reserve),
managing authority from the operator tag or the designation; facilities by amenity/healthcare/office.
Features the rules cannot use are left out and counted in the file QA report.

## 3. Licences

Nothing about a licence is assumed. The pipeline refuses to build, and the database QA refuses to
publish, when:

| Rule | Build (`check_licences`) | Database QA (not waivable) |
|---|---|---|
| A source's review was rejected | refused | `licence.rejected` error |
| The licence does not permit commercial use and no written permission is recorded | refused | refused by the manifest |
| The licence is restricted (WDPA/WDPCA, UNEP-WCMC, `-NC`, `-ND`) without written permission | refused | `licence.restricted` error |
| Production: a source is not reviewed and approved | refused | `licence.unreviewed` error (info for other purposes) |
| Production: placeholder or synthetic data | refused | `content.synthetic` error |

**WDPA** is not used. Its terms forbid commercial use and redistribution without written permission from
UNEP-WCMC; the development release takes protected areas from OpenStreetMap, production from the
Department of Wildlife Conservation and the Forest Department. A deployment that obtains permission
records it in `permission_reference` (see the commented block in `production.example.toml`).

Obligations are carried with the data:

* the licence, attribution, commercial use, redistribution and share-alike flags are **copied into
  every load** (`meta.dataset_load`), so a later change to a source does not rewrite history;
* `GET /geo/v1/layers` lists the attribution of each layer and of the whole catalogue; the map client
  shows it in its attribution control; exports carry it (`attribution`);
* data whose licence does not allow redistribution is **not exported**: `GET /geo/v1/layers/{code}/export`
  answers `403 export_not_permitted`, and the catalogue marks the layer `exportable: false`;
* `SOURCES.md` in every release directory lists sources, licences, obligations and original files.

## 4. Coordinate reference systems

Everything is stored in EPSG:4326 (and a generated EPSG:5235 twin for metric work). For each source:

1. **The source CRS is never guessed.** It comes from the file; a profile's `source_crs` must agree with
   it; a file without one needs `source_crs`; a CRS without an EPSG code must be declared explicitly.
2. **The operation is chosen by PROJ** (`TransformerGroup`): the most accurate one available, with its
   published accuracy (SLD99 → WGS 84: 14 m; Kandawala → WGS 84: 35 m). Missing PROJ grids or a
   *ballpark* operation stop the build unless the profile pins or allows one.
3. **The operation is verified.** The pipeline transforms sample points with `ogr2ogr -ct <pipeline>` (as
   it transforms the data) and with pyproj; they must agree to about a centimetre (a wrong axis order
   shows up as kilometres). Control points must land within their tolerance of their surveyed position.
4. **It is recorded**: `coordinate_operation` in the load (description, accuracy, PROJ version and the
   pipeline itself), and the file QA report.

## 5. Lineage: what every dataset records

| Required | Where (`meta.dataset_load`, view `meta.dataset_lineage`, `GET /geo/v1/releases/{code}`) |
|---|---|
| Source | `source_id` → `meta.data_source` (code, name, publisher, URL) |
| Licence | `licence`, `licence_url`, `attribution`, `commercial_use_allowed`, `redistribution_allowed`, `share_alike`, `permission_reference`, `licence_review_status` (as at import) |
| Source URL / reference | `source_reference` (the exact file or delivery), `original_file`, `original_checksum_sha256`, `source_retrieved_at` |
| Source version | `source_version` (e.g. the OSM replication timestamp read from the PBF header) |
| Import timestamp | `started_at` / `finished_at` (`imported_at` in the view), `loaded_by`, `loader_version` |
| Geometry type | `geometry_types` (of what was loaded), `extent` |
| CRS | `source_crs`, `storage_crs` (EPSG:4326), `coordinate_operation`, `transformation` |
| Accuracy | `geometry_accuracy_m` (required, > 0), `geometry_source` |
| Data release ID | `release_id` → `meta.ref_data_release.code`, e.g. `ref-2026.09-dev` |

Plus counts (`source_feature_count`, `loaded_count`, `repaired_count`, `rejected_count`), the GIS-ready
file and its checksum (`source_file`, `source_checksum_sha256`), the tool versions (GDAL, PROJ,
GeoPandas, Shapely, pyproj, pyogrio) and the file QA report. `build.json` records the build itself
(profile checksum, tool versions, every original file with checksum and how it was retrieved).

## 6. Quality assurance

### File QA (at build time, per dataset)

`qa/<dataset>.qa.json`, stored with the load. Features that cannot be loaded are left out and counted:

| Check | Severity |
|---|---|
| `crs.storage`, `crs.operation` | error / info (the operation applied and its verification) |
| `geometry.empty`, `geometry.type` (not a type the layer holds), `geometry.unrepairable` | warning, left out |
| `geometry.invalid` (Shapely; kept, the database repairs it) | warning |
| `identifier.missing`, `identifier.duplicate`, `identifier.name_missing` | warning, left out |
| `duplicate.geometry` | warning |
| `outlier.service_area` (with a hint when latitude and longitude look swapped) | warning, left out |
| `outlier.extent`, `outlier.coverage`, `outlier.vertices`, `outlier.count` | error / warning |
| `outlier.rejected` (share of features left out above `max_rejected_ratio`) | error, else info |

A dataset whose file QA fails is still written (so the report can be read), the build fails, and the
loader refuses the file.

### Database QA (after loading, before publishing)

`python -m app.pipeline qa C` (run by `load`). Results in `meta.qa_run` and `meta.qa_finding`; the run
records a fingerprint of the release's content. Checks (`app/services/reference_qa.py`, 40 in all):

| Family | Checks |
|---|---|
| CRS consistency | `crs.storage_srid`, `crs.metric_srid` (errors), `crs.mixed_sources` |
| Invalid geometries | `geometry.invalid` (`ST_IsValid`, with `ST_IsValidReason` and location; error), `geometry.repaired` (repairs made on load with `ST_MakeValid`, logged in `meta.geometry_repair`, rated by how far the boundary moved and how much the area changed), `geometry.degenerate`, `geometry.sliver`, `geometry.complexity`, `geometry.spike` |
| Duplicate features | `duplicate.geometry` (per admin level for admin areas), `duplicate.near` (same name and type within a distance), `duplicate.overlap` |
| Missing identifiers | `identifier.missing` (error), `identifier.code_format`, `identifier.name_missing` |
| Geometry outliers, unexpected extents | `outlier.extent` (error), `outlier.coverage`, `outlier.area`, `outlier.count` (error), `outlier.count_change` (against the current release), `outlier.rejected`, `outlier.outside_country` |
| Topology | `topology.admin_parent` (admin area inside its parent), `topology.admin_overlap`, `topology.admin_gap` (parent covered by its children), `topology.settlement_unlinked` |
| Licences, metadata, content | `licence.*`, `metadata.*`, `content.synthetic`, `release.*`, `artifact.sources_missing` |

Thresholds come from the layer defaults and the dataset's `qa` expectations in the manifest.

**Repair procedure.** Invalid polygons are repaired on load with
`ST_MakeValid(g, 'method=structure keepcollapsed=false')`; the original geometry, the reason and the
repair are logged in `meta.geometry_repair`, and QA rates each repair (info below 1 m of boundary shift
and 0.1 % of area, warning above, error above 100 m). Geometries that are still invalid are errors that
cannot be waived. A polygon that collapses when repaired is left out at build time.

**Waivers.** An error that is waivable can be accepted with a reason:
`python -m app.pipeline waive C FINDING --reason "..."`. The database records who and when, refuses a
waiver without a reason or of a check that cannot be waived (licences, CRS, invalid geometry, incomplete
loads, synthetic data in production), and writes `reference_release.qa_waiver` to the audit log.

### What the sample release's QA says

`ref-2026.09-dev`: 0 errors, 178 warnings, 45 notes. The warnings are real properties of the open
sources, left visible rather than hidden: `topology.admin_parent` 95 and `topology.admin_gap` 33 (the
DS and GN divisions come from OCHA/Survey Department, the provinces and districts from OpenStreetMap:
their boundaries do not coincide), `geometry.degenerate` 22 (OSM road segments under 1 m),
`duplicate.overlap` 19 and `duplicate.near` 8 (OSM water bodies and facilities mapped twice),
`outlier.outside_country` 1.

## 7. Releases

A release is a versioned, immutable set of reference data. Codes follow `ref-YYYY.MM[-suffix]`
(`ref-2026.10`, `ref-2026.09-dev`); a release has a **purpose**: `production`, `development` or `test`.

```
draft ──publish──► published ──retire──► retired
                     │
                     └── current (exactly one; the release used when a request names none)
```

* Data can be loaded only into a draft; published releases do not change (database triggers).
* **Publish gate.** A draft is published only when its latest database QA run is *fresh* (its content
  fingerprint equals `meta.release_fingerprint()` now) and has no unwaived errors. Loading more data
  after QA makes the run stale.
* A production environment (`GIS_ENV=production`) only makes a **production** release current.
* **Events keep their release.** The geo-context of every event stores the code of the release it was
  computed with (`refDataRelease`, `geo.event_geo_context.release_code`); making another release current
  does not rewrite it. `POST /geo/v1/enrich` can name a release (`?refDataRelease=`).
* `GET /geo/v1/releases` and `GET /geo/v1/releases/{code}` (permission `map:read`) list the published
  releases and show, for one, every dataset's lineage and licence, the basemap artifacts and the QA
  result ([API](../api/releases.md)).
* `python -m app.pipeline diff C --against R` compares feature counts and identifiers.

## 8. Basemap

`python -m app.pipeline basemap --profile P --release C` writes `data/basemap/<release>/`:

| File | What |
|---|---|
| `<name>.pmtiles` | Vector tiles (MVT in PMTiles, EPSG:3857), z0-14, written by GDAL: land, landcover, protected areas, water, waterways, boundaries, railways, roads and places, with the zoom levels in `app/pipeline/basemap.py` |
| `style.json` | MapLibre style; sources use `pmtiles://<public_path>/<release>/<name>.pmtiles`; carries the attribution |
| `fonts/<font>/<range>.pbf`, `glyphs.json` | Glyphs (Noto Sans, OFL-1.1) with checksums |
| `artifacts.json` | Each file with checksum, size, zooms, bounds and the sources it was made from |

Load it with the release (`load DIR --basemap data/basemap/<release>`, or `artifacts C DIR` while the
release is a draft): the files are recorded in `meta.release_artifact` with their sources and licences,
and QA checks them. Serve the directory as static files at `public_path` (`/basemap`) with HTTP range
requests; point the map client at the style (`VITE_BASEMAP_STYLE_URL`). The client's own labels use the
basemap's font (`Noto Sans Regular`).

Labels use Latin-script names (`name:en` or `name`): MapLibre cannot shape Sinhala or Tamil, so those
names are kept in the tiles (`name_si`, `name_ta`) but not drawn.

## 9. Building the development release from sources

```bash
cd backend
pip install -e '.[pipeline]'          # and gdal-bin >= 3.8
python -m app.pipeline fetch --profile ../data/pipeline/profiles/dev.toml
python -m app.pipeline run --profile ../data/pipeline/profiles/dev.toml --basemap --current
```

`fetch` downloads the geoBoundaries files and the OpenStreetMap extract from Geofabrik
(`https://download.geofabrik.de/asia/sri-lanka-latest.osm.pbf`, about 145 MB), verifies the checksums the
profile states and records each file's provenance next to it (`<file>.provenance.json`). A file placed in
`data/raw/` by hand is used as it is (its modification time is recorded as the retrieval time, and that
basis is stated). The release build is deterministic: the same inputs give byte-identical data files
(the basemap's tiles are not - GDAL writes them in parallel - so `artifacts.json` records the checksums of
the files actually built). The build and the basemap take about a minute each, loading and QA one to
two minutes.

With Docker: `docker compose --profile pipeline run --rm pipeline build --profile /srv/data/pipeline/profiles/dev.toml`
(the service mounts `data/`).

## 10. Production

1. Copy `production.example.toml`, name each agency delivery, its layer and field mapping, CRS and
   control points.
2. For every source record the licence as the agreement states it, whether commercial use and
   redistribution are allowed, any written permission, and the review (who, when, reference); set
   `status = "approved"` only after that review.
3. Place the deliveries in the raw directory (or set `download_env` / `auth_header_env`) and state their
   SHA-256.
4. `run --profile production.toml --basemap`; read `SOURCES.md` and the QA report; fix the data or waive
   what is acceptable with a reason; `publish C --current` with `GIS_ENV=production`.

Risk zones have no open source for Sri Lanka: the development release uses five labelled placeholders
(`DEV PLACEHOLDER ...`), which QA reports as synthetic and which cannot reach production. Production
risk zones come from NBRO, DMC and DWC under agreement.

## 11. Troubleshooting

| Symptom | Cause |
|---|---|
| `LicenceError` before anything is built | A source is unreviewed (production), restricted, non-commercial without permission, or rejected: fix the profile, do not change the check |
| `does not guess coordinate systems` | The file has no CRS: declare `source_crs` after checking it |
| `ogr2ogr and pyproj disagree` | Wrong axis order or pipeline; pin the operation or fix `source_crs` |
| `needs PROJ grids that are not installed` | `projsync --all` (or pin an operation) |
| `changed since it was retrieved` | The raw file differs from its provenance record; remove the `.provenance.json` if the new file is intended |
| `has not been checked` / `changed after its last QA run` | Run `qa C` before `publish` |
| `unresolved QA errors` | Fix the data, or `waive` each acceptable finding with a reason |
| `a production environment only serves production releases` | Load a production release, or run with a non-production `GIS_ENV` |
| Map shows no basemap | `data/basemap/<release>` missing, or `VITE_BASEMAP_STYLE_URL` not set; a 404 on `/basemap/...` means the directory is not served |
| `export_not_permitted` | The layer's source does not allow redistribution |
