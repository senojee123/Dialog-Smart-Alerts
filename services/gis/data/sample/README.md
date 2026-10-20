# Development sample

Everything needed to run the whole application locally, without GDAL or downloads.

| Path | Content |
|---|---|
| `ref-2026.09-dev/` | Reference data release `ref-2026.09-dev` (purpose `development`), built by the pipeline from `data/pipeline/profiles/dev.toml`: 17 datasets, 37 235 features. Lineage in `manifest.json` and `build.json`, licences and attribution in [`SOURCES.md`](ref-2026.09-dev/SOURCES.md), one QA report per dataset in `qa/`. |
| `operational/wildlife-dept.json` | A development tenant (`wildlife-dept`): 5 sites and 6 devices on the A6 and A11 around Habarana, with fields of view; 3 geofences (a circle at Habarana junction, a corridor along the A11 at Minneriya National Park, a polygon around Palugaswewa); 10 events over 24 hours. Invented and labelled: names start with `DEV`, attributes carry `sample: true`. |

The basemap of the release (`lka.pmtiles`, style and glyphs, 22 MB) lives in
`data/basemap/ref-2026.09-dev/`; it is delivered with the working copy rather than committed, and can be
rebuilt with `python -m app.pipeline basemap --profile ../data/pipeline/profiles/dev.toml --release
ref-2026.09-dev` from the OpenStreetMap extract.

## Load it

```bash
docker compose --profile sample run --rm sample-data
```

or, from `backend/` with the `GIS_DB_*` settings of both logins:

```bash
python -m app.pipeline load ../data/sample/ref-2026.09-dev --basemap ../data/basemap/ref-2026.09-dev --current
python -m app.tools.seed_dev_data ../data/sample/operational/wildlife-dept.json
```

## What is in the release

| Layer | Datasets | Source | Licence |
|---|---|---|---|
| Administrative areas | country, 9 provinces, 25 districts, 330 DS divisions (national); 548 GN divisions (pilot area) | geoBoundaries gbOpen (ADM0-2 from OpenStreetMap; ADM3-4 from OCHA ROAP and the Survey Department) | ODbL 1.0; CC BY 3.0 IGO |
| Settlements | 404 cities and towns (national), 201 villages and hamlets (pilot) | OpenStreetMap | ODbL 1.0 |
| Facilities | 1 333 police, hospitals, fire stations, wildlife and forest offices (national); 269 schools, offices, places of worship (pilot) | OpenStreetMap | ODbL 1.0 |
| Roads | 20 839 motorways, trunk, primary, secondary and tertiary roads (national); 8 316 local roads and tracks (pilot) | OpenStreetMap | ODbL 1.0 |
| Rivers and water bodies | 2 018 rivers, 2 045 reservoirs, tanks, lakes, lagoons and wetlands of 10 ha or more (national); 385 streams and canals, 469 smaller water bodies (pilot) | OpenStreetMap | ODbL 1.0 |
| Protected areas | 38 national parks, sanctuaries, nature and forest reserves | OpenStreetMap (not WDPA) | ODbL 1.0 |
| Risk zones | 5 labelled placeholders (`DEV PLACEHOLDER ...`) | GIS Core Service | CC0 1.0 |

The pilot area is `[80.45, 7.75, 81.10, 8.30]` (Habarana, Dambulla, Sigiriya, Minneriya, Polonnaruwa).
OpenStreetMap data as of 2026-09-22T20:22:59Z (replication sequence 4631). Database QA: 0 errors,
178 warnings (mostly OCHA and OSM boundaries that do not nest exactly), 45 notes - see
[pipeline.md](../../docs/reference-data/pipeline.md#what-the-sample-releases-qa-says).

This is **development** data: licences are not reviewed for production use, OpenStreetMap is not
authoritative, and the risk zones are not real. A production environment refuses to make it current.
