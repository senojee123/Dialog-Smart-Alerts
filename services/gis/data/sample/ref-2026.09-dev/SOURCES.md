# Reference data release `ref-2026.09-dev` (development)

Development sample: geoBoundaries and OpenStreetMap (open data) with labelled placeholder risk zones; not for operational use

Built by the reference data pipeline (`python -m app.pipeline build`). The lineage of every file is in
`manifest.json` and `build.json`; the QA report of every dataset is in `qa/`.

## Sources, licences and attribution

| Source | Licence | Commercial use | Redistribution | Review | Attribution | Version | Datasets |
|---|---|---|---|---|---|---|---|
| geoBoundaries gbOpen Sri Lanka ADM0 (country) (William & Mary geoLab (geoBoundaries); OpenStreetMap contributors) | [ODbL-1.0](https://opendatacommons.org/licenses/odbl/1-0/) (share-alike) | yes | yes | unreviewed | © OpenStreetMap contributors (ODbL); geoBoundaries, Runfola et al. (2020), PLoS ONE 15(4): e0231866 | geoBoundaries gbOpen LKA-ADM0-54457186 (built 2023-12-12; source updated 2023-01-19) | `admin-l0-country.geojson.gz` |
| geoBoundaries gbOpen Sri Lanka ADM1 (provinces) (William & Mary geoLab (geoBoundaries); OpenStreetMap contributors) | [ODbL-1.0](https://opendatacommons.org/licenses/odbl/1-0/) (share-alike) | yes | yes | unreviewed | © OpenStreetMap contributors (ODbL); geoBoundaries, Runfola et al. (2020), PLoS ONE 15(4): e0231866 | geoBoundaries gbOpen LKA-ADM1-99731895 (built 2023-12-12; source updated 2023-01-19) | `admin-l1-provinces.geojson.gz` |
| geoBoundaries gbOpen Sri Lanka ADM2 (districts) (William & Mary geoLab (geoBoundaries); OpenStreetMap contributors) | [ODbL-1.0](https://opendatacommons.org/licenses/odbl/1-0/) (share-alike) | yes | yes | unreviewed | © OpenStreetMap contributors (ODbL); geoBoundaries, Runfola et al. (2020), PLoS ONE 15(4): e0231866 | geoBoundaries gbOpen LKA-ADM2-46371173 (built 2023-12-12; source updated 2023-01-19) | `admin-l2-districts.geojson.gz` |
| geoBoundaries gbOpen Sri Lanka ADM3 (divisional secretariat divisions) (William & Mary geoLab (geoBoundaries); OCHA ROAP; Survey Department of Sri Lanka) | [CC-BY-3.0-IGO](https://creativecommons.org/licenses/by/3.0/igo/) | yes | yes | unreviewed | OCHA ROAP; Survey Department of Sri Lanka (CC BY 3.0 IGO); geoBoundaries, Runfola et al. (2020) | geoBoundaries gbOpen LKA-ADM3-8540358 (built 2023-12-12; source updated 2023-01-19) | `admin-l3-ds-divisions.geojson.gz` |
| geoBoundaries gbOpen Sri Lanka ADM4 (Grama Niladhari divisions) (William & Mary geoLab (geoBoundaries); OCHA ROAP; Survey Department of Sri Lanka) | [CC-BY-3.0-IGO](https://creativecommons.org/licenses/by/3.0/igo/) | yes | yes | unreviewed | OCHA ROAP; Survey Department of Sri Lanka (CC BY 3.0 IGO); geoBoundaries, Runfola et al. (2020) | geoBoundaries gbOpen LKA-ADM4-91002919 (built 2023-12-12; source updated 2023-01-19) | `admin-l4-gn-divisions-pilot.geojson.gz` |
| GIS Core Service development placeholders (GIS Core Service project) | [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/) | yes | yes | unreviewed | Development placeholders; not real data | 1 (data/pipeline/placeholders/build.py) | `risk-zones-placeholder.geojson.gz` |
| OpenStreetMap, Sri Lanka extract (OpenStreetMap contributors; extract by Geofabrik GmbH) | [ODbL-1.0](https://opendatacommons.org/licenses/odbl/1-0/) (share-alike) | yes | yes | unreviewed | © OpenStreetMap contributors | OpenStreetMap data as of 2026-09-22T20:22:59Z (replication sequence 4631) | `settlements-towns.geojson.gz`, `settlements-villages-pilot.geojson.gz`, `facilities-emergency.geojson.gz`, `facilities-civic-pilot.geojson.gz`, `roads-national.geojson.gz`, `roads-local-pilot.geojson.gz`, `rivers-national.geojson.gz`, `waterways-pilot.geojson.gz`, `water-areas-national.geojson.gz`, `water-areas-pilot.geojson.gz`, `protected-areas.geojson.gz` |

## Original files

| Source | File | SHA-256 | Retrieved | From |
|---|---|---|---|---|
| geoboundaries-lka-adm0 | `geoBoundaries-LKA-ADM0_simplified.geojson` | `e895a2e5c5fd8e1b323801dc60ab04a14bdecb3a312ecfee7952cd7c25d41bdd` | 2026-09-24T08:23:53.496593+00:00 (file modification time (the file was placed in the raw directory by hand)) | https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA/ADM0/geoBoundaries-LKA-ADM0_simplified.geojson |
| geoboundaries-lka-adm1 | `geoBoundaries-LKA-ADM1_simplified.geojson` | `aef852a66d3502fa98d02e0c361ab7aef614cfd62f7f05d7c8da1f16dfa6f4d0` | 2026-09-24T08:23:51.749481+00:00 (file modification time (the file was placed in the raw directory by hand)) | https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA/ADM1/geoBoundaries-LKA-ADM1_simplified.geojson |
| geoboundaries-lka-adm2 | `geoBoundaries-LKA-ADM2_simplified.geojson` | `90c7e2940f78f85d9810a1f0915627b660a2b6efe381c2becf245b4cbaa8286c` | 2026-09-24T08:23:52.032593+00:00 (file modification time (the file was placed in the raw directory by hand)) | https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA/ADM2/geoBoundaries-LKA-ADM2_simplified.geojson |
| geoboundaries-lka-adm3 | `geoBoundaries-LKA-ADM3_simplified.geojson` | `8b7ada3e7df25c43a422e40f9005b8e1ec378dbe87599c192dc663de4f409e9d` | 2026-09-24T08:23:52.076593+00:00 (file modification time (the file was placed in the raw directory by hand)) | https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA/ADM3/geoBoundaries-LKA-ADM3_simplified.geojson |
| geoboundaries-lka-adm4 | `geoBoundaries-LKA-ADM4_simplified.geojson` | `82b3c6caea09c9cfe5286b05272499e11a2c52dd8b8b85fab56e6b097a90bfe9` | 2026-09-24T08:23:52.872593+00:00 (file modification time (the file was placed in the raw directory by hand)) | https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA/ADM4/geoBoundaries-LKA-ADM4_simplified.geojson |
| gis-core-dev-placeholders | `dev_risk_zones.geojson` | `c82032f7d498c22b7566608a0efaaf772d07e3bb1f9e0a81386e223040985f45` | 2026-09-24T08:23:41.927663+00:00 (file modification time (the file is kept next to the profile)) | dev_risk_zones.geojson |
| osm-geofabrik-lka | `sri-lanka-latest.osm.pbf` | `522169dd6bfafb47e5a8760a0a8800c19a3df3307d98f6f2f9be4cb94ec6a2b8` | 2026-09-23T10:19:45+00:00 (file modification time (the file was placed in the raw directory by hand)) | https://download.geofabrik.de/asia/sri-lanka-latest.osm.pbf |

## Datasets

| File | Layer | Features | Left out | File QA |
|---|---|---|---|---|
| `admin-l0-country.geojson.gz` | ref.admin_area | 1 | 0 | passed |
| `admin-l1-provinces.geojson.gz` | ref.admin_area | 9 | 0 | passed |
| `admin-l2-districts.geojson.gz` | ref.admin_area | 25 | 0 | passed |
| `admin-l3-ds-divisions.geojson.gz` | ref.admin_area | 330 | 0 | passed |
| `admin-l4-gn-divisions-pilot.geojson.gz` | ref.admin_area | 548 | 0 | passed |
| `settlements-towns.geojson.gz` | ref.settlement | 404 | 0 | passed |
| `settlements-villages-pilot.geojson.gz` | ref.settlement | 201 | 0 | passed |
| `facilities-emergency.geojson.gz` | ref.facility | 1333 | 0 | passed |
| `facilities-civic-pilot.geojson.gz` | ref.facility | 269 | 0 | passed |
| `roads-national.geojson.gz` | ref.road | 20839 | 1 | warnings |
| `roads-local-pilot.geojson.gz` | ref.road | 8316 | 0 | passed |
| `rivers-national.geojson.gz` | ref.water_body | 2018 | 0 | passed |
| `waterways-pilot.geojson.gz` | ref.water_body | 385 | 0 | passed |
| `water-areas-national.geojson.gz` | ref.water_body | 2045 | 0 | warnings |
| `water-areas-pilot.geojson.gz` | ref.water_body | 469 | 0 | passed |
| `protected-areas.geojson.gz` | ref.protected_area | 38 | 0 | passed |
| `risk-zones-placeholder.geojson.gz` | ref.risk_zone | 5 | 0 | passed |

## Obligations and notes

* geoboundaries-lka-adm0: ODbL-1.0 is share-alike; derived databases shared outside the platform must be offered under the same licence
* geoboundaries-lka-adm1: ODbL-1.0 is share-alike; derived databases shared outside the platform must be offered under the same licence
* geoboundaries-lka-adm2: ODbL-1.0 is share-alike; derived databases shared outside the platform must be offered under the same licence
* osm-geofabrik-lka: ODbL-1.0 is share-alike; derived databases shared outside the platform must be offered under the same licence
* This is a **development** release: licences are not reviewed for production use and it may contain labelled placeholders. It cannot be made current in a production environment.
