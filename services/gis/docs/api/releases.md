# Reference data releases API

Where reference data comes from. Every reference feature belongs to a **release** (`ref-YYYY.MM[-suffix]`);
these endpoints list the published releases and show, for one, the lineage and licence of every dataset
in it, the basemap files built for it and the QA result it was published with. How releases are built,
checked and published: [../reference-data/pipeline.md](../reference-data/pipeline.md).

| Endpoint | Permission | Answer |
|---|---|---|
| `GET /geo/v1/releases` | `map:read` (scope `gis:read`) | Published and retired releases, the current one first. Drafts are not listed. |
| `GET /geo/v1/releases/{code}` | `map:read` | One release with its datasets, artifacts, attribution and QA. `404 release_not_found` for an unknown code or a draft. |

Both are cached privately for 60 seconds. Reads of releases are not tenant data and are not written to
the audit log.

## `GET /geo/v1/releases`

```json
{
  "releases": [
    {
      "code": "ref-2026.09-dev",
      "status": "published",
      "purpose": "development",
      "isCurrent": true,
      "description": "Development sample: geoBoundaries and OpenStreetMap (open data) with labelled placeholder risk zones; not for operational use",
      "publishedAt": "2026-09-24T10:45:27.961889Z",
      "retiredAt": null,
      "datasets": 17,
      "features": 37235
    }
  ]
}
```

`purpose` is `production`, `development` or `test`. A production deployment only makes a production
release current.

## `GET /geo/v1/releases/{code}`

The summary above, plus:

| Member | Content |
|---|---|
| `attribution` | Every attribution the release's sources require, without repeats: show it wherever the data is shown |
| `datasetLineage` | One entry per loaded file (below) |
| `artifacts` | Files built for the release (basemap tiles, style, glyphs) with checksum, size, zooms and their sources and licences |
| `qa` | The database QA run the release was published after: `status`, `checks`, `errors`, `warnings`, `infos`, `waivedErrors`, `finishedAt` |

A `datasetLineage` entry, as recorded when the data was imported:

```json
{
  "layer": "ref.road",
  "source": "osm-geofabrik-lka",
  "sourceName": "OpenStreetMap, Sri Lanka extract",
  "publisher": "OpenStreetMap contributors; extract by Geofabrik GmbH",
  "licence": "ODbL-1.0",
  "licenceUrl": "https://opendatacommons.org/licenses/odbl/1-0/",
  "attribution": "© OpenStreetMap contributors",
  "commercialUseAllowed": true,
  "redistributionAllowed": true,
  "shareAlike": true,
  "licenceReview": "unreviewed",
  "sourceReference": "https://download.geofabrik.de/asia/sri-lanka-latest.osm.pbf",
  "sourceVersion": "OpenStreetMap data as of 2026-09-22T20:22:59Z (replication sequence 4631)",
  "sourceRetrievedAt": "2026-09-23T10:19:45Z",
  "sourceFile": "roads-local-pilot.geojson.gz",
  "sourceChecksumSha256": "42d142f1...",
  "originalFile": "sri-lanka-latest.osm.pbf",
  "originalChecksumSha256": "522169dd...",
  "sourceCrs": "EPSG:4326",
  "storageCrs": "EPSG:4326",
  "coordinateOperation": null,
  "transformation": "GDAL 3.8.4 OSM driver (app/pipeline/osmconf.ini) to GeoPackage; highway ways; ...",
  "geometryTypes": ["MULTILINESTRING"],
  "geometryAccuracyM": 20.0,
  "sourceFeatures": 8316,
  "loaded": 8316,
  "repaired": 0,
  "rejected": 0,
  "importedAt": "2026-09-24T10:43:45.130302Z",
  "finishedAt": "2026-09-24T10:45:17.512501Z"
}
```

For a source in another CRS, `coordinateOperation` names the operation applied, its published accuracy,
the PROJ version and the PROJ pipeline, e.g. `Inverse of SLD99 to WGS 84 (1) ... (accuracy 14 m; PROJ
9.x): +proj=pipeline ...`.

## Licences in the other endpoints

* `GET /geo/v1/layers`: each layer has `attribution` (what its sources require) and `exportable`; the
  catalogue has `attribution` for all of them. Operational layers (the tenant's own data) have none.
* `GET /geo/v1/layers/{code}/export`: the export carries `attribution`. When a source of the layer does
  not allow redistribution, the export is refused:

  ```json
  {
    "type": "urn:gis-core-service:problem:export_not_permitted",
    "title": "The licence of this data does not permit exports",
    "status": 403,
    "detail": "the licence of roads-no-redistribution does not allow ref.road to leave the platform",
    "layer": "ref.road",
    "sources": ["roads-no-redistribution"],
    "refDataRelease": "ref-2026.09-restricted"
  }
  ```

  Reading the layer on the map is still allowed.
* `POST /geo/v1/enrich`: every geo-context names the release it was computed with (`refDataRelease`) and
  keeps it; `?refDataRelease=` computes against another published release.
