"""Build the ``lka_open`` reference data fixture from openly licensed sources.

Downloads (or reads from ``--raw-dir``) the source files listed in ``SOURCES``, verifies their SHA-256
checksums, extracts the pilot subset and writes GIS-ready GeoJSON files, ``manifest.json`` (for
``python -m app.tools.load_reference_data``) and ``SOURCES.md`` (licences, attribution, checksums).

Run from ``backend/`` with the backend environment (needs Shapely)::

    python ../data/fixtures/lka_open/build.py                 # download into data/raw/lka_open
    python ../data/fixtures/lka_open/build.py --raw-dir DIR   # use files already downloaded

Subset:

* provinces and districts: all (geoBoundaries gbOpen, from OpenStreetMap)
* DS divisions: those in the Anuradhapura and Polonnaruwa districts (pilot area)
* GN divisions: those in Palugaswewa DS division, which contains Habarana
* settlements: Natural Earth populated places in Sri Lanka
* roads, rivers, lakes and reservoirs: Natural Earth features in the service area (roads clipped to it)

Sub-areas are selected by representative point (``point_on_surface``). Coordinates are not altered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import box, mapping, shape

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[2]
DEFAULT_RAW_DIR = REPOSITORY_ROOT / "data" / "raw" / "lka_open"
SERVICE_AREA = box(79.44, 5.66, 82.15, 10.08)
PILOT_DISTRICTS = ("Anuradhapura District", "Polonnaruwa District")
PILOT_DS_POINT = shapely.Point(80.749, 8.037)  # Habarana

GB = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/LKA"
NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"

# file name -> (URL, SHA-256 of the file as downloaded on 2026-09-15)
SOURCES: dict[str, tuple[str, str]] = {
    "geoBoundaries-LKA-ADM1_simplified.geojson": (
        f"{GB}/ADM1/geoBoundaries-LKA-ADM1_simplified.geojson",
        "aef852a66d3502fa98d02e0c361ab7aef614cfd62f7f05d7c8da1f16dfa6f4d0",
    ),
    "geoBoundaries-LKA-ADM2_simplified.geojson": (
        f"{GB}/ADM2/geoBoundaries-LKA-ADM2_simplified.geojson",
        "90c7e2940f78f85d9810a1f0915627b660a2b6efe381c2becf245b4cbaa8286c",
    ),
    "geoBoundaries-LKA-ADM3_simplified.geojson": (
        f"{GB}/ADM3/geoBoundaries-LKA-ADM3_simplified.geojson",
        "8b7ada3e7df25c43a422e40f9005b8e1ec378dbe87599c192dc663de4f409e9d",
    ),
    "geoBoundaries-LKA-ADM4_simplified.geojson": (
        f"{GB}/ADM4/geoBoundaries-LKA-ADM4_simplified.geojson",
        "82b3c6caea09c9cfe5286b05272499e11a2c52dd8b8b85fab56e6b097a90bfe9",
    ),
    "ne_10m_populated_places_simple.geojson": (
        f"{NE}/ne_10m_populated_places_simple.geojson",
        "fd3fa867a320cbd5c5b6bb5bc550afeec2939fb2cef688e508007282a55ac42f",
    ),
    "ne_10m_roads.geojson": (
        f"{NE}/ne_10m_roads.geojson",
        "66a0c7b438e92fd124822cc5921cfa11042f48c294ade5e0f03f2c6640fd0248",
    ),
    "ne_10m_rivers_lake_centerlines.geojson": (
        f"{NE}/ne_10m_rivers_lake_centerlines.geojson",
        "bb854a900ecbd3b408df46d5e16e3e0f974ba55993f9d8b5c26e855273c0905a",
    ),
    "ne_10m_lakes.geojson": (
        f"{NE}/ne_10m_lakes.geojson",
        "2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9",
    ),
}

MANIFEST_SOURCES = [
    {
        "code": "geoboundaries-lka-osm",
        "name": "geoBoundaries gbOpen Sri Lanka ADM1-ADM2 (from OpenStreetMap)",
        "publisher": "William & Mary geoLab (geoBoundaries); OpenStreetMap contributors",
        "url": "https://www.geoboundaries.org/",
        "licence": "ODbL-1.0",
        "licenceUrl": "https://opendatacommons.org/licenses/odbl/1-0/",
        "attribution": "© OpenStreetMap contributors (ODbL); geoBoundaries, Runfola et al. (2020), "
        "PLoS ONE 15(4): e0231866",
        "commercialUseAllowed": True,
        "redistributionAllowed": True,
        "shareAlike": True,
        "notes": "Boundary year 2017 (source: OpenStreetMap, Wambacher). Simplified geometry. "
        "Derived databases must be offered under ODbL.",
    },
    {
        "code": "geoboundaries-lka-ocha",
        "name": "geoBoundaries gbOpen Sri Lanka ADM3-ADM4 (OCHA ROAP / Survey Department)",
        "publisher": "William & Mary geoLab (geoBoundaries); OCHA ROAP; Survey Department of Sri Lanka",
        "url": "https://data.humdata.org/dataset/sri-lanka-administrative-levels-0-4-boundaries",
        "licence": "CC-BY-3.0-IGO",
        "licenceUrl": "https://creativecommons.org/licenses/by/3.0/igo/",
        "attribution": "OCHA ROAP; Survey Department of Sri Lanka (CC BY 3.0 IGO); geoBoundaries, "
        "Runfola et al. (2020)",
        "commercialUseAllowed": True,
        "redistributionAllowed": True,
        "notes": "DS divisions 2020, GN divisions 2019. Simplified geometry. No official codes in this "
        "extract; the geoBoundaries shape ID is used as the code.",
    },
    {
        "code": "natural-earth-10m",
        "name": "Natural Earth 1:10m cultural and physical vectors",
        "publisher": "Natural Earth",
        "url": "https://www.naturalearthdata.com/",
        "licence": "public-domain",
        "licenceUrl": "https://www.naturalearthdata.com/about/terms-of-use/",
        "attribution": "Made with Natural Earth",
        "commercialUseAllowed": True,
        "redistributionAllowed": True,
        "notes": "Small-scale (1:10 million) data: positions are only indicative (about 1 km).",
    },
]


# Loader instructions per output file (see app/services/reference_loader.py).
TRANSFORMATION_OSM = "none: source is EPSG:4326 GeoJSON (RFC 7946); geoBoundaries simplified geometry"
FILES = [
    {
        "path": "admin_areas_level1.geojson",
        "sourceReference": SOURCES["geoBoundaries-LKA-ADM1_simplified.geojson"][0],
        "originalFile": "geoBoundaries-LKA-ADM1_simplified.geojson",
        "originalChecksumSha256": SOURCES["geoBoundaries-LKA-ADM1_simplified.geojson"][1],
        "layer": "ref.admin_area",
        "source": "geoboundaries-lka-osm",
        "sourceVersion": "geoBoundaries gbOpen LKA-ADM1-99731895 (boundary year 2017)",
        "transformation": TRANSFORMATION_OSM,
        "geometrySource": "osm",
        "geometryAccuracyM": 100,
        "properties": {"level": 1},
    },
    {
        "path": "admin_areas_level2.geojson",
        "sourceReference": SOURCES["geoBoundaries-LKA-ADM2_simplified.geojson"][0],
        "originalFile": "geoBoundaries-LKA-ADM2_simplified.geojson",
        "originalChecksumSha256": SOURCES["geoBoundaries-LKA-ADM2_simplified.geojson"][1],
        "layer": "ref.admin_area",
        "source": "geoboundaries-lka-osm",
        "sourceVersion": "geoBoundaries gbOpen LKA-ADM2 (boundary year 2017)",
        "transformation": TRANSFORMATION_OSM,
        "geometrySource": "osm",
        "geometryAccuracyM": 100,
        "properties": {"level": 2},
        "parentBy": "code",
    },
    {
        "path": "admin_areas_level3_pilot.geojson",
        "sourceReference": SOURCES["geoBoundaries-LKA-ADM3_simplified.geojson"][0],
        "originalFile": "geoBoundaries-LKA-ADM3_simplified.geojson",
        "originalChecksumSha256": SOURCES["geoBoundaries-LKA-ADM3_simplified.geojson"][1],
        "layer": "ref.admin_area",
        "source": "geoboundaries-lka-ocha",
        "sourceVersion": "geoBoundaries gbOpen LKA-ADM3-8540358 (boundary year 2020)",
        "transformation": TRANSFORMATION_OSM + "; subset: DS divisions of Anuradhapura and Polonnaruwa",
        "geometrySource": "digitised",
        "geometryAccuracyM": 100,
        "properties": {"level": 3},
        "parentBy": "location",
    },
    {
        "path": "admin_areas_level4_palugaswewa.geojson",
        "sourceReference": SOURCES["geoBoundaries-LKA-ADM4_simplified.geojson"][0],
        "originalFile": "geoBoundaries-LKA-ADM4_simplified.geojson",
        "originalChecksumSha256": SOURCES["geoBoundaries-LKA-ADM4_simplified.geojson"][1],
        "layer": "ref.admin_area",
        "source": "geoboundaries-lka-ocha",
        "sourceVersion": "geoBoundaries gbOpen LKA-ADM4-91002919 (boundary year 2019)",
        "transformation": TRANSFORMATION_OSM + "; subset: GN divisions of Palugaswewa DS division",
        "geometrySource": "digitised",
        "geometryAccuracyM": 50,
        "properties": {"level": 4},
        "parentBy": "location",
    },
    {
        "path": "settlements.geojson",
        "sourceReference": SOURCES["ne_10m_populated_places_simple.geojson"][0],
        "originalFile": "ne_10m_populated_places_simple.geojson",
        "originalChecksumSha256": SOURCES["ne_10m_populated_places_simple.geojson"][1],
        "layer": "ref.settlement",
        "source": "natural-earth-10m",
        "sourceVersion": "Natural Earth ne_10m_populated_places_simple (5.x)",
        "transformation": "none: source is EPSG:4326; subset: adm0_a3 = LKA",
        "geometrySource": "digitised",
        "geometryAccuracyM": 1000,
        "adminAreaBy": "location",
    },
    {
        "path": "roads.geojson",
        "sourceReference": SOURCES["ne_10m_roads.geojson"][0],
        "originalFile": "ne_10m_roads.geojson",
        "originalChecksumSha256": SOURCES["ne_10m_roads.geojson"][1],
        "layer": "ref.road",
        "source": "natural-earth-10m",
        "sourceVersion": "Natural Earth ne_10m_roads (5.x)",
        "transformation": "none: source is EPSG:4326; clipped to the service area",
        "geometrySource": "digitised",
        "geometryAccuracyM": 1000,
    },
    {
        "path": "water_bodies.geojson",
        "sourceReference": SOURCES["ne_10m_rivers_lake_centerlines.geojson"][0]
        + " ; "
        + SOURCES["ne_10m_lakes.geojson"][0],
        "layer": "ref.water_body",
        "source": "natural-earth-10m",
        "sourceVersion": "Natural Earth ne_10m_rivers_lake_centerlines and ne_10m_lakes (5.x)",
        "transformation": "none: source is EPSG:4326; features inside the service area",
        "geometrySource": "digitised",
        "geometryAccuracyM": 1000,
    },
]

SOURCES_MD = """# `lka_open` reference data fixture

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
{licence_rows}

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
{source_rows}

## Output files

| File | Features | SHA-256 |
|---|---|---|
{output_rows}
"""


LICENCE_ROWS = [
    (
        "`admin_areas_level1.geojson` (provinces), `admin_areas_level2.geojson` (districts)",
        "geoBoundaries gbOpen LKA ADM1/ADM2, derived from OpenStreetMap (boundary year 2017)",
        "ODbL 1.0 (share-alike)",
        "© OpenStreetMap contributors; geoBoundaries (Runfola et al. 2020, PLoS ONE 15(4): e0231866)",
    ),
    (
        "`admin_areas_level3_pilot.geojson` (DS divisions of Anuradhapura and Polonnaruwa), "
        "`admin_areas_level4_palugaswewa.geojson` (GN divisions of Palugaswewa, which contains Habarana)",
        "geoBoundaries gbOpen LKA ADM3/ADM4, from OCHA ROAP and the Survey Department of Sri Lanka "
        "(2020/2019)",
        "CC BY 3.0 IGO",
        "OCHA ROAP; Survey Department of Sri Lanka; geoBoundaries",
    ),
    (
        "`settlements.geojson`, `roads.geojson`, `water_bodies.geojson`",
        "Natural Earth 1:10m populated places, roads, rivers and lake centre lines, lakes",
        "Public domain",
        "Made with Natural Earth",
    ),
]


def write_manifest(outputs: list[dict[str, Any]], checksums: dict[str, str]) -> None:
    manifest = {
        "release": {
            "code": "ref-2026.09-lka-open",
            "purpose": "test",
            "description": "Open Sri Lankan reference data fixture (geoBoundaries, Natural Earth)",
        },
        "sources": MANIFEST_SOURCES,
        "files": FILES,
    }
    (HERE / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    source_rows = "\n".join(
        f"| `{name}` | {url} | `{checksums[name]}` |" for name, (url, _) in SOURCES.items()
    )
    output_rows = "\n".join(
        f"| `{item['file']}` | {item['features']} | `{item['sha256']}` |" for item in outputs
    )
    licence_rows = "\n".join("| " + " | ".join(row) + " |" for row in LICENCE_ROWS)
    (HERE / "SOURCES.md").write_text(
        SOURCES_MD.format(licence_rows=licence_rows, source_rows=source_rows, output_rows=output_rows),
        encoding="utf-8",
    )


def download(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name, (url, _) in SOURCES.items():
        target = raw_dir / name
        if target.exists():
            continue
        print(f"downloading {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - fixed https URLs
            target.write_bytes(response.read())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(raw_dir: Path, name: str) -> list[dict[str, Any]]:
    path = raw_dir / name
    expected = SOURCES[name][1]
    actual = sha256(path)
    if expected and actual != expected:
        raise SystemExit(f"checksum mismatch for {name}: expected {expected}, got {actual}")
    features: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["features"]
    return features


def feature(fid: str, geometry: Any, properties: dict[str, Any]) -> dict[str, Any]:
    geo = geometry if isinstance(geometry, dict) else mapping(geometry)
    return {"type": "Feature", "id": fid, "properties": properties, "geometry": geo}


def write(name: str, features: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(features, key=lambda item: str(item["id"]))
    payload = {"type": "FeatureCollection", "features": ordered}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=list) + "\n"
    (HERE / name).write_text(text, encoding="utf-8")
    return {"file": name, "features": len(ordered), "sha256": hashlib.sha256(text.encode()).hexdigest()}


def within(parts: list[shapely.Geometry]) -> Callable[[dict[str, Any]], bool]:
    def test(item: dict[str, Any]) -> bool:
        point = shapely.point_on_surface(shape(item["geometry"]))
        return any(part.contains(point) for part in parts)

    return test


def build(raw_dir: Path) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []

    adm1 = read(raw_dir, "geoBoundaries-LKA-ADM1_simplified.geojson")
    outputs.append(
        write(
            "admin_areas_level1.geojson",
            (
                feature(
                    f["properties"]["shapeID"],
                    f["geometry"],
                    {
                        "name": f["properties"]["shapeName"],
                        "code": f["properties"]["shapeISO"],
                    },
                )
                for f in adm1
            ),
        )
    )

    adm2 = read(raw_dir, "geoBoundaries-LKA-ADM2_simplified.geojson")
    outputs.append(
        write(
            "admin_areas_level2.geojson",
            (
                feature(
                    f["properties"]["shapeID"],
                    f["geometry"],
                    {
                        "name": f["properties"]["shapeName"],
                        "code": f["properties"]["shapeISO"],
                        # ISO 3166-2:LK district codes start with the province number: LK-71 -> LK-7.
                        "parent_code": f["properties"]["shapeISO"][:4],
                    },
                )
                for f in adm2
            ),
        )
    )

    districts = {f["properties"]["shapeName"]: shape(f["geometry"]) for f in adm2}
    adm3 = read(raw_dir, "geoBoundaries-LKA-ADM3_simplified.geojson")
    pilot_ds = [f for f in adm3 if within([districts[name] for name in PILOT_DISTRICTS])(f)]
    outputs.append(
        write(
            "admin_areas_level3_pilot.geojson",
            (
                feature(
                    f["properties"]["shapeID"],
                    f["geometry"],
                    {
                        "name": f["properties"]["shapeName"],
                        "code": f["properties"]["shapeID"],
                    },
                )
                for f in pilot_ds
            ),
        )
    )

    habarana_ds = [shape(f["geometry"]) for f in adm3 if shape(f["geometry"]).contains(PILOT_DS_POINT)]
    adm4 = read(raw_dir, "geoBoundaries-LKA-ADM4_simplified.geojson")
    outputs.append(
        write(
            "admin_areas_level4_palugaswewa.geojson",
            (
                feature(
                    f["properties"]["shapeID"],
                    f["geometry"],
                    {
                        "name": f["properties"]["shapeName"],
                        "code": f["properties"]["shapeID"],
                    },
                )
                for f in adm4
                if within(habarana_ds)(f)
            ),
        )
    )

    places = read(raw_dir, "ne_10m_populated_places_simple.geojson")
    capitals = {"Admin-0 capital", "Admin-0 capital alt"}
    outputs.append(
        write(
            "settlements.geojson",
            (
                feature(
                    str(p["properties"]["ne_id"]),
                    p["geometry"],
                    {
                        "name": p["properties"]["name"],
                        "settlement_type": "capital"
                        if p["properties"]["featurecla"] in capitals
                        else ("city" if p["properties"]["pop_max"] >= 100_000 else "town"),
                        "population": int(p["properties"]["pop_max"]),
                        "featurecla": p["properties"]["featurecla"],
                        "adm1name": p["properties"]["adm1name"],
                    },
                )
                for p in places
                if p["properties"].get("adm0_a3") == "LKA"
            ),
        )
    )

    roads = read(raw_dir, "ne_10m_roads.geojson")
    road_features = []
    for r in roads:
        geometry = shape(r["geometry"])
        if not geometry.intersects(SERVICE_AREA):
            continue
        clipped = shapely.line_merge(shapely.intersection(geometry, SERVICE_AREA))
        road_features.append(
            feature(
                str(r["properties"]["rwdb_rd_id"]),
                clipped,
                {
                    "road_class": "unknown",
                    "ne_type": r["properties"]["type"],
                    "length_km": r["properties"]["length_km"],
                    "scalerank": r["properties"]["scalerank"],
                    "clipped_to_service_area": not SERVICE_AREA.contains(geometry),
                },
            )
        )
    outputs.append(write("roads.geojson", road_features))

    rivers = read(raw_dir, "ne_10m_rivers_lake_centerlines.geojson")
    lakes = read(raw_dir, "ne_10m_lakes.geojson")
    water = [
        feature(
            f"river-{f['properties']['dissolve']}",
            f["geometry"],
            {
                "name": f["properties"].get("name"),
                "water_type": "river",
                "featurecla": f["properties"]["featurecla"],
            },
        )
        for f in rivers
        if SERVICE_AREA.contains(shape(f["geometry"]))
    ] + [
        feature(
            str(f["properties"]["ne_id"]),
            f["geometry"],
            {
                "name": f["properties"].get("name"),
                "water_type": "reservoir" if f["properties"]["featurecla"] == "Reservoir" else "lake",
                "featurecla": f["properties"]["featurecla"],
                "dam_name": f["properties"].get("dam_name"),
            },
        )
        for f in lakes
        if SERVICE_AREA.contains(shape(f["geometry"]))
    ]
    outputs.append(write("water_bodies.geojson", water))
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--no-download", action="store_true", help="fail instead of downloading")
    args = parser.parse_args()
    if not args.no_download:
        download(args.raw_dir)
    outputs = build(args.raw_dir)
    checksums = {name: sha256(args.raw_dir / name) for name in SOURCES}
    write_manifest(outputs, checksums)
    print(json.dumps({"outputs": outputs, "sources": checksums}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
