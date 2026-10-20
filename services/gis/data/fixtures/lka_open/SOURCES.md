# `lka_open` reference data fixture

Openly licensed Sri Lankan reference data for integration tests and local development. Built by
`build.py` from the files below; load it with

```bash
cd backend
python -m app.tools.load_reference_data ../data/fixtures/lka_open/manifest.json --current
```

The geometries are simplified or small-scale. They are good enough to exercise real boundaries,
multipolygons and nearest-feature queries, not for operational decisions.

## Sources and licences

| Output | Source | Licence | Attribution |
|---|---|---|---|
| `admin_areas_level1.geojson` (provinces), `admin_areas_level2.geojson` (districts) | geoBoundaries gbOpen LKA ADM1/ADM2, derived from OpenStreetMap (boundary year 2017) | ODbL 1.0 (share-alike) | © OpenStreetMap contributors; geoBoundaries (Runfola et al. 2020, PLoS ONE 15(4): e0231866) |
| `admin_areas_level3_pilot.geojson` (DS divisions of Anuradhapura and Polonnaruwa), `admin_areas_level4_palugaswewa.geojson` (GN divisions of Palugaswewa, which contains Habarana) | geoBoundaries gbOpen LKA ADM3/ADM4, from OCHA ROAP and the Survey Department of Sri Lanka (2020/2019) | CC BY 3.0 IGO | OCHA ROAP; Survey Department of Sri Lanka; geoBoundaries |
| `settlements.geojson`, `roads.geojson`, `water_bodies.geojson` | Natural Earth 1:10m populated places, roads, rivers and lake centre lines, lakes | Public domain | Made with Natural Earth |

Notes:

* The OSM-derived and OCHA-derived levels come from different sources, so their boundaries do not
  nest exactly. The loader links DS and GN divisions to their parent by representative point.
* The ADM3/ADM4 extract carries no official P-codes; the geoBoundaries shape ID is used as the code.
* Natural Earth positions are indicative only (about 1 km). The loader records 1000 m accuracy.
* Natural Earth spells Puttalam as "Puttalan"; source names are kept unchanged.
* **Protected areas and risk zones are not included.** No openly licensed authoritative source was
  available: WDPA (Protected Planet) does not permit commercial use without written permission from
  UNEP-WCMC, and `meta.data_source` refuses such a source unless `permission_reference` is recorded.
  Obtain DWC and Forest Department boundaries under agreement. The synthetic fixture
  (`../synthetic_habarana`) covers these layers for tests.

## Source files

| File | URL | SHA-256 |
|---|---|---|
| `geoBoundaries-LKA-ADM1_simplified.geojson` | https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA/ADM1/geoBoundaries-LKA-ADM1_simplified.geojson | `aef852a66d3502fa98d02e0c361ab7aef614cfd62f7f05d7c8da1f16dfa6f4d0` |
| `geoBoundaries-LKA-ADM2_simplified.geojson` | https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA/ADM2/geoBoundaries-LKA-ADM2_simplified.geojson | `90c7e2940f78f85d9810a1f0915627b660a2b6efe381c2becf245b4cbaa8286c` |
| `geoBoundaries-LKA-ADM3_simplified.geojson` | https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA/ADM3/geoBoundaries-LKA-ADM3_simplified.geojson | `8b7ada3e7df25c43a422e40f9005b8e1ec378dbe87599c192dc663de4f409e9d` |
| `geoBoundaries-LKA-ADM4_simplified.geojson` | https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA/ADM4/geoBoundaries-LKA-ADM4_simplified.geojson | `82b3c6caea09c9cfe5286b05272499e11a2c52dd8b8b85fab56e6b097a90bfe9` |
| `ne_10m_populated_places_simple.geojson` | https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places_simple.geojson | `fd3fa867a320cbd5c5b6bb5bc550afeec2939fb2cef688e508007282a55ac42f` |
| `ne_10m_roads.geojson` | https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_roads.geojson | `66a0c7b438e92fd124822cc5921cfa11042f48c294ade5e0f03f2c6640fd0248` |
| `ne_10m_rivers_lake_centerlines.geojson` | https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_rivers_lake_centerlines.geojson | `bb854a900ecbd3b408df46d5e16e3e0f974ba55993f9d8b5c26e855273c0905a` |
| `ne_10m_lakes.geojson` | https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_lakes.geojson | `2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9` |

## Output files

| File | Features | SHA-256 |
|---|---|---|
| `admin_areas_level1.geojson` | 9 | `22c235c4be5bed5b3e7e1ff31a3ebeda17eacf7cfe74ea9819c8c6b3d544dd4f` |
| `admin_areas_level2.geojson` | 25 | `eab94fd8cb36940116f1c6cd6b0b379835bd3bc8a16d3e8c4f7d5ac05c3afde9` |
| `admin_areas_level3_pilot.geojson` | 29 | `c3650d92dddafd83a95c30c7957f65e7ae9b7f73b2b30e4426588634132ea26a` |
| `admin_areas_level4_palugaswewa.geojson` | 16 | `6af373f52590995dafed3ba9082a00862d6b8d26ec19b57be8665bca5ffca2dc` |
| `settlements.geojson` | 14 | `8ae57881dd05f836b40d9d245b45d8d99b3a91eaff799f74287e804e3a5b2937` |
| `roads.geojson` | 41 | `9182480fce75c23841374871c9084fb962cb8ad54f9022ba9d6d653d49849de6` |
| `water_bodies.geojson` | 7 | `1bc498c5c269acca63e63b4f9692ec341bc1863f3cf6fb051b8217b320b991f2` |
