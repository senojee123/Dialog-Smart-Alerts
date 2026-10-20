# ADR-0018: Reference data pipeline - profiles, lineage, QA gate and releases

* Status: accepted
* Date: 2026-09-24
* Refines: plan §5.4 (reference data), §8 (basemap), R4 (coordinate systems); ADR-0013 (spatial data
  model), ADR-0014 (geo-context keeps its release)

## Context

The service answers questions against reference data: administrative boundaries, settlements,
facilities, roads, protected areas, risk zones, rivers and water bodies, and draws them over a basemap.
Until now releases were loaded from hand-made fixtures. A repeatable way was needed to go from source
files to PostGIS, with these forces:

* **Sources differ by deployment.** Development needs openly licensed data that anyone can download;
  production uses agency deliveries (Survey Department, DWC, Forest Department, RDA, Irrigation, NBRO,
  DMC) under agreements whose terms are not known in advance.
* **Licences must not be assumed.** WDPA forbids commercial use and redistribution without written
  permission; OpenStreetMap (ODbL) requires attribution and share-alike for derived databases; an agency
  may not allow its data to leave the platform.
* **Coordinates.** Agency data is often in SLD99 (EPSG:5235) or Kandawala (EPSG:5234); the published
  operations to WGS 84 are accurate to 14 m and 35 m, need the right axis order, and a wrong one fails
  silently by kilometres.
* **Trust.** An event enriched in September must still say which data it was enriched with after the
  data changes; a release that fails its checks must not reach users; every feature must be traceable
  to a source, a licence, a version and a file.
* No open source exists for Sri Lankan risk zones, yet the application must run end to end locally.

## Decision

1. **Profiles are data.** A TOML profile names every source (licence, attribution, commercial use,
   redistribution, share-alike, written permission, licence review, file, download URL or environment
   variable, checksum, version, CRS, pinned operation, control points) and every dataset (layer, adapter,
   field mapping, area, nominal accuracy, QA expectations). The code contains no source. `dev.toml`
   builds the development release; `production.example.toml` is a template that refuses to build until
   every licence has been reviewed.
2. **Licences are checked twice and never assumed.** The build refuses restricted licences (WDPA,
   non-commercial, no-derivatives) without recorded permission, rejected reviews, and - for production -
   unreviewed sources and placeholders. The database QA repeats these as errors that cannot be waived.
   Licence terms are copied into every load; exports of data that may not be redistributed are refused;
   attribution is served with the layer catalogue and shown on the map.
3. **GDAL, GeoPandas, Shapely and pyproj, each for what it does best.** ogr2ogr reads every format and
   applies coordinate operations (and GDAL writes the vector tiles); GeoPandas and Shapely map and check
   features; pyproj chooses the operation. The pipeline never guesses a CRS, records the operation and
   its accuracy, and verifies it by transforming sample points with both ogr2ogr and pyproj (they must
   agree to a centimetre) and by control points when a profile has them.
4. **Build, then load.** The build writes a self-describing release directory (`manifest.json` with
   full lineage per file, deterministic gzipped GeoJSON, a file QA report per dataset, `build.json`,
   `SOURCES.md`); the loader needs no GDAL. A directory can be reviewed, versioned (the development
   sample is in git), copied between environments and loaded again with identical results.
5. **Two QA stages and a publish gate.** File QA at build time (types, identifiers, duplicates, extent,
   counts, service area, invalid polygons); database QA after loading, in SQL on PostGIS (`ST_IsValid`,
   repairs made with `ST_MakeValid` and their effect, duplicates, identifiers, outliers, extents, counts
   against the current release, admin topology, CRS, licences, artifacts). A draft is published only when
   its latest QA run is fresh (same content fingerprint) and has no unwaived errors; waivers need a reason
   and are audited; some checks cannot be waived.
6. **Releases are immutable and purposeful.** `ref-YYYY.MM[-suffix]`, purpose production, development or
   test; draft → published → retired; one current release; a production environment only makes a
   production release current. Every stored geo-context keeps the code of the release it was computed
   with.
7. **Placeholders are labelled, not disguised.** Where no open source exists (risk zones), the
   development profile uses a handful of obviously artificial shapes named `DEV PLACEHOLDER ...`, marked
   synthetic; they are reported by QA and cannot reach production.
8. **A development sample ships with the repository**: the built `ref-2026.09-dev` release (open data,
   11 MB), its basemap (PMTiles, 22 MB, delivered next to it) and a tenant's sample objects, loaded by one
   command through the same loader, QA and services as production data.

## Consequences

* A new deployment changes profiles, not code. Onboarding an agency dataset is a field mapping and a
  licence review.
* Nothing reaches production without a recorded licence review, and the checks are enforced by the
  database as well as the tools. The price is ceremony for development-only data (reviews stay
  `unreviewed`, which QA notes but accepts outside production).
* The pipeline has heavy dependencies (GDAL ≥ 3.8, GeoPandas); they are an optional extra and a separate
  Docker target, so the API image stays small.
* The development release carries real warnings (OCHA and OSM boundaries do not nest perfectly, OSM has
  duplicates and tiny segments). They are left visible: they are what the QA is for.
* To test: licence refusal (build and QA), CRS resolution and verification, file QA, determinism, the
  publish gate (unchecked, stale, unwaived errors, waivers and their audit), the production environment
  rule, lineage completeness, the releases API, export refusal and attribution, and that seeded events
  keep their release (`tests/unit/test_pipeline_config.py`, `tests/pipeline/`,
  `tests/integration/test_reference_releases*.py`, `test_seed_dev_data.py`).
