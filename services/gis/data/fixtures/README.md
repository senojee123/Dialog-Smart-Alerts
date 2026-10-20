# Test fixtures

Small, versioned reference data for the integration tests. Each fixture is a manifest plus GIS-ready
GeoJSON files (release purpose `test`), loaded with the same loader as production data. To run the
application locally, use the fuller development sample in [`../sample/`](../sample/README.md) instead.

```bash
cd backend
python -m app.tools.load_reference_data ../data/fixtures/lka_open/manifest.json --current
python -m app.tools.load_reference_data ../data/fixtures/synthetic_habarana/manifest.json --publish
```

| Fixture | Origin | Licence | Used for |
|---|---|---|---|
| [`lka_open/`](lka_open/SOURCES.md) | Extract of geoBoundaries (OpenStreetMap; OCHA ROAP and Survey Department) and Natural Earth, built by `lka_open/build.py` from checksum-pinned downloads | ODbL 1.0, CC BY 3.0 IGO, public domain (attribution in `SOURCES.md`) | Real boundaries, multipolygons and coastlines; admin hierarchy of Habarana; nearest towns and roads |
| [`synthetic_habarana/`](synthetic_habarana/README.md) | Constructed geometry, built by `synthetic_habarana/build.py` | CC0-1.0 | Exact answers: boundary points, enclaves, time-dependent zones, repaired and rejected geometries |

Rules:

* Keep fixtures small (the whole directory is under 1 MB) and deterministic (sorted, no timestamps).
* Record the source, licence, attribution and checksums of every extract next to it.
* Never commit tenant data or personal data. Operational fixtures are created by the tests.
* In these fixtures protected areas and risk zones exist only in the synthetic world. The development
  sample takes protected areas from OpenStreetMap (ODbL) - not from WDPA, which does not permit
  commercial use or redistribution without written permission - and has labelled placeholder risk
  zones, for which no open source exists.
