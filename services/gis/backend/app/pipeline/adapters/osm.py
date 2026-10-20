"""The ``osm`` adapter: OpenStreetMap extracts, staged with GDAL and classified by tag rules.

The extract (PBF) is staged once per file into a GeoPackage by GDAL's OSM driver with the pipeline's
``osmconf.ini`` (three ogr2ogr runs: points, lines, areas, each filtered to the tags the pipeline uses).
Themes then read the staged layers with GeoPandas and map OSM tags to the layer schema. The rules are
plain functions (:func:`facility_type`, :func:`road_class`, :func:`water_type`, :func:`protected_area`,
:func:`settlement_type`) so that they can be read and tested; where a value is inferred rather than
tagged, the feature's attributes say so (``*_basis``).

OpenStreetMap is ODbL-licensed: attribution is required, and a derived database shared outside the
platform must be offered under the ODbL. It is not authoritative: protected areas, facilities and admin
boundaries from agencies replace it in production profiles.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

import geopandas as gpd
import pandas as pd
import pyogrio

from app.pipeline import gdal
from app.pipeline.acquire import AcquiredSource
from app.pipeline.adapters import BuildContext, Extracted, Note
from app.pipeline.crs import choose_operation
from app.pipeline.errors import ProfileError
from app.pipeline.features import METRIC, clean, frame, integer, metric_area, select_area, text, year
from app.pipeline.profile import BBox, DatasetConfig, SourceConfig

OSMCONF: Final = Path(__file__).resolve().parent.parent / "osmconf.ini"
STAGING_FILTERS: Final[Mapping[str, str]] = {
    "points": "place IS NOT NULL OR amenity IS NOT NULL OR healthcare IS NOT NULL OR office IS NOT NULL",
    "lines": "highway IS NOT NULL OR waterway IS NOT NULL OR railway IS NOT NULL",
    "multipolygons": (
        'boundary IS NOT NULL OR leisure IS NOT NULL OR "natural" IS NOT NULL OR water IS NOT NULL '
        "OR landuse IS NOT NULL OR amenity IS NOT NULL OR healthcare IS NOT NULL OR office IS NOT NULL "
        "OR place IS NOT NULL OR wetland IS NOT NULL"
    ),
}
STAGING_CONFIG: Final[Mapping[str, str]] = {
    # Broken multipolygon relations are left out rather than closed silently.
    "OGR_GEOMETRY_ACCEPT_UNCLOSED_RING": "NO",
    "OSM_MAX_TMPFILE_SIZE": "1024",
}

WILDLIFE: Final = re.compile(r"wild\s*life|\bDWC\b", re.IGNORECASE)
FOREST: Final = re.compile(r"forest", re.IGNORECASE)
COAST: Final = re.compile(r"coast\s+conservation", re.IGNORECASE)
TANK: Final = re.compile(r"\b(wewa|wewe|tank|kulam|kulama)\b", re.IGNORECASE)
ROAD_REF: Final = re.compile(r"^\s*([EABCD])\s*-?\s*(\d+)", re.IGNORECASE)
LOCAL_HIGHWAYS: Final = frozenset({"residential", "unclassified", "living_street", "service", "road"})
IUCN: Final[Mapping[str, str]] = {
    "1a": "Ia", "ia": "Ia", "1b": "Ib", "ib": "Ib", "2": "II", "ii": "II", "3": "III", "iii": "III",
    "4": "IV", "iv": "IV", "5": "V", "v": "V", "6": "VI", "vi": "VI",
}  # fmt: skip
DESIGNATIONS: Final = (
    ("Strict Nature Reserve", re.compile(r"strict\s+nature\s+reserve", re.I), "DWC"),
    ("National Park", re.compile(r"national\s+park", re.I), "DWC"),
    ("Marine Sanctuary", re.compile(r"marine\s+sanctuary", re.I), "DWC"),
    ("Sanctuary", re.compile(r"sanctuary", re.I), "DWC"),
    ("Nature Reserve", re.compile(r"nature\s+reserve", re.I), "DWC"),
    ("Jungle Corridor", re.compile(r"jungle\s+corridor", re.I), "DWC"),
    ("Conservation Forest", re.compile(r"conservation\s+forest", re.I), "FD"),
    ("Forest Reserve", re.compile(r"(forest\s+reserve|reserved?\s+forest)", re.I), "FD"),
)
PROTECT_CLASS_DESIGNATION: Final[Mapping[str, str]] = {
    "Ia": "Strict Nature Reserve",
    "Ib": "Nature Reserve",
    "II": "National Park",
    "IV": "Sanctuary",
}
FACILITY_LABELS: Final[Mapping[str, str]] = {
    "police_station": "Police station",
    "hospital": "Hospital",
    "school": "School",
    "fire_station": "Fire station",
    "wildlife_office": "Wildlife office",
    "forest_office": "Forest office",
    "government_office": "Government office",
    "place_of_worship": "Place of worship",
}


def _t(tags: Mapping[str, Any], key: str) -> str | None:
    return text(tags.get(key))


# --- tag rules ------------------------------------------------------------------------------------------


def settlement_type(tags: Mapping[str, Any]) -> str | None:
    place = (_t(tags, "place") or "").lower()
    if place not in ("city", "town", "village", "hamlet"):
        return None
    if _t(tags, "capital") == "yes" or _t(tags, "admin_level") == "2":
        return "capital"
    return place


def facility_type(tags: Mapping[str, Any]) -> str | None:
    amenity = (_t(tags, "amenity") or "").lower()
    healthcare = (_t(tags, "healthcare") or "").lower()
    office = (_t(tags, "office") or "").lower()
    described = " ".join(filter(None, (_t(tags, "operator"), _t(tags, "name"))))
    if amenity == "police":
        return "police_station"
    if amenity == "hospital" or healthcare == "hospital":
        return "hospital"
    if amenity == "fire_station":
        return "fire_station"
    if amenity == "ranger_station":
        return "forest_office" if FOREST.search(described) else "wildlife_office"
    if office == "government" or amenity == "townhall":
        if WILDLIFE.search(described):
            return "wildlife_office"
        if FOREST.search(described):
            return "forest_office"
        return "government_office"
    if amenity == "school":
        return "school"
    if amenity == "place_of_worship":
        return "place_of_worship"
    return None


def road_class(highway: str | None, ref: str | None) -> tuple[str, str]:
    """RDA class and the basis it was taken from: the route number, or the OSM highway type."""
    if ref:
        match = ROAD_REF.match(ref.split(";")[0])
        if match:
            return match.group(1).upper(), "ref"
    kind = (highway or "").lower()
    if kind in ("motorway", "motorway_link"):
        return "E", "highway"
    if kind in LOCAL_HIGHWAYS:
        return "local", "highway"
    if kind == "track":
        return "track", "highway"
    return "unknown", "highway"


def water_type(tags: Mapping[str, Any]) -> tuple[str, str]:
    """Water type and its basis. Sri Lankan irrigation tanks (wewa, kulam) are named, rarely tagged."""
    water = (_t(tags, "water") or "").lower()
    name = " ".join(filter(None, (_t(tags, "name"), _t(tags, "name_en"))))
    if _t(tags, "natural") == "wetland" or _t(tags, "wetland"):
        return "wetland", "natural=wetland"
    if water == "tank" or TANK.search(name):
        return "tank", "name or water=tank"
    if _t(tags, "landuse") == "reservoir" or water == "reservoir":
        return "reservoir", "water/landuse=reservoir"
    if water in ("lake", "lagoon", "river", "canal"):
        return water, f"water={water}"
    return "other", f"water={water or 'unspecified'}"


def protected_area(tags: Mapping[str, Any]) -> dict[str, Any] | str:
    """Columns of a protected area, or the reason the feature is not one we can use."""
    name = _t(tags, "name")
    if name is None:
        return "no name"
    protect_class = (_t(tags, "protect_class") or _t(tags, "iucn_level") or "").lower()
    iucn = IUCN.get(protect_class)
    title = _t(tags, "protection_title") or _t(tags, "designation")
    described = " ".join(filter(None, (title, name)))
    designation: str | None = None
    authority: str | None = None
    for label, pattern, managing in DESIGNATIONS:
        if pattern.search(described):
            designation, authority = label, managing
            break
    if designation is None and iucn is not None and iucn in PROTECT_CLASS_DESIGNATION:
        designation, authority = PROTECT_CLASS_DESIGNATION[iucn], "DWC"
    if designation is None and _t(tags, "boundary") == "national_park":
        designation, authority = "National Park", "DWC"
    if designation is None:
        return "not a recognised designation (national park, sanctuary, nature or forest reserve, ...)"
    operator = _t(tags, "operator") or ""
    if WILDLIFE.search(operator):
        managing, basis = "DWC", "operator tag"
    elif FOREST.search(operator):
        managing, basis = "FD", "operator tag"
    elif COAST.search(operator):
        managing, basis = "CCD", "operator tag"
    else:
        managing = authority or "other"
        basis = "inferred from the designation (Fauna and Flora Protection Ordinance / Forest Ordinance)"
    return {
        "name": name,
        "designation": designation,
        "managing_authority": managing,
        "iucn_category": iucn or "not_reported",
        "osm_managing_authority_basis": basis,
        "osm_protect_class": _t(tags, "protect_class"),
        "osm_protection_title": title,
    }


# --- staging ------------------------------------------------------------------------------------------


def stage(context: BuildContext, acquired: AcquiredSource) -> Path:
    """The OSM extract as a GeoPackage (points, lines, multipolygons), built once per file and config."""
    config_digest = hashlib.sha256(OSMCONF.read_bytes()).hexdigest()
    key = hashlib.sha256(
        f"{acquired.sha256}:{config_digest}:{sorted(STAGING_FILTERS.items())}".encode()
    ).hexdigest()
    target = context.staging_dir / f"osm-{key[:16]}.gpkg"
    marker = target.with_suffix(".json")
    if target.exists() and marker.exists():
        return target
    target.unlink(missing_ok=True)
    area = context.profile.area("national") if "national" in context.profile.areas else None
    for layer, where in STAGING_FILTERS.items():
        gdal.translate(
            gdal.Translate(
                source=str(acquired.path),
                destination=target,
                destination_layer=layer,
                source_layers=[layer],
                spatial_filter=area,
                where=where,
                open_options={"CONFIG_FILE": str(OSMCONF)},
                config=STAGING_CONFIG,
                append=target.exists(),
            )
        )
    marker.write_text(
        json.dumps(
            {
                "source": acquired.code,
                "sha256": acquired.sha256,
                "osmconf": config_digest,
                "gdal": gdal.version_string(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target


def read_staged(staged: Path, layer: str, where: str, area: BBox, columns: list[str]) -> gpd.GeoDataFrame:
    return pyogrio.read_dataframe(staged, layer=layer, where=where, bbox=area, columns=columns)


def _quote(values: list[str]) -> str:
    for value in values:
        if not re.fullmatch(r"[A-Za-z0-9_:-]+", value):
            raise ProfileError(f"invalid OSM class {value!r}")
    return ", ".join(f"'{value}'" for value in values)


def _names(tags: Mapping[str, Any]) -> dict[str, Any]:
    """English name (Sri Lankan OSM uses ``name`` for English), with Sinhala and Tamil where tagged."""
    return {
        "name": _t(tags, "name_en") or _t(tags, "name"),
        "name_si": _t(tags, "name_si"),
        "name_ta": _t(tags, "name_ta"),
    }


def _element_id(row: Mapping[str, Any], layer: str) -> str:
    if layer == "multipolygons":
        way = text(row.get("osm_way_id"))
        return f"osm-way-{way}" if way else f"osm-relation-{text(row.get('osm_id'))}"
    kind = "node" if layer == "points" else "way"
    return f"osm-{kind}-{text(row.get('osm_id'))}"


# --- themes -------------------------------------------------------------------------------------------

POINT_COLUMNS: Final = [
    "osm_id", "name", "name_en", "name_si", "name_ta", "place", "population", "population_date", "capital",
    "amenity", "healthcare", "office", "government", "operator", "admin_level", "wikidata",
]  # fmt: skip
LINE_COLUMNS: Final = [
    "osm_id",
    "name",
    "name_en",
    "name_si",
    "name_ta",
    "highway",
    "ref",
    "waterway",
    "intermittent",
]
AREA_COLUMNS: Final = [
    "osm_id", "osm_way_id", "name", "name_en", "name_si", "name_ta", "amenity", "healthcare", "office",
    "government", "operator", "boundary", "protect_class", "protection_title", "designation", "iucn_level",
    "leisure", "natural", "water", "wetland", "landuse", "wikidata",
]  # fmt: skip


def _settlements(staged: Path, dataset: DatasetConfig, area: BBox, notes: list[Note]) -> gpd.GeoDataFrame:
    classes = dataset.classes or ["city", "town", "village", "hamlet"]
    data = read_staged(staged, "points", f"place IN ({_quote(classes)})", area, POINT_COLUMNS)
    records = []
    for row in data.to_dict("records"):
        identifier = _element_id(row, "points")
        kind = settlement_type(row)
        names = _names(row)
        if kind is None or names["name"] is None:
            notes.append(Note("transform.skipped", "place without a name left out", identifier))
            continue
        population = integer(row.get("population"))
        properties = {
            **names,
            "settlement_type": kind,
            "population": population,
            "population_year": year(row.get("population_date")) if population is not None else None,
            "osm_place": _t(row, "place"),
            "wikidata": _t(row, "wikidata"),
        }
        records.append((identifier, clean(properties), row["geometry"]))
    return frame(records)


def _facilities(staged: Path, dataset: DatasetConfig, area: BBox, notes: list[Note]) -> gpd.GeoDataFrame:
    if not dataset.classes:
        raise ProfileError(f"dataset {dataset.name}: list the facility types to keep (classes)")
    unknown = sorted(set(dataset.classes) - set(FACILITY_LABELS))
    if unknown:
        raise ProfileError(f"dataset {dataset.name}: unknown facility types {', '.join(unknown)}")
    where = (
        "amenity IN ('police', 'hospital', 'fire_station', 'ranger_station', 'townhall', 'school', "
        "'place_of_worship') OR healthcare = 'hospital' OR office = 'government'"
    )
    points = read_staged(staged, "points", where, area, POINT_COLUMNS)
    areas = read_staged(staged, "multipolygons", where, area, AREA_COLUMNS)
    records: list[tuple[str, dict[str, Any], Any, str]] = []
    for layer, data in (("points", points), ("multipolygons", areas)):
        for row in data.to_dict("records"):
            kind = facility_type(row)
            if kind is None or kind not in dataset.classes:
                continue
            identifier = _element_id(row, layer)
            names = _names(row)
            properties: dict[str, Any] = {**names, "facility_type": kind, "operator": _t(row, "operator")}
            if names["name"] is None:
                properties["name"] = f"{FACILITY_LABELS[kind]} (unnamed in OpenStreetMap)"
                properties["osm_unnamed"] = True
            geometry = row["geometry"]
            if layer == "multipolygons":
                properties["osm_geometry_basis"] = "point on the surface of the mapped area"
                geometry = geometry.representative_point()
            records.append((identifier, clean(properties), geometry, layer))
    result = frame((identifier, properties, geometry) for identifier, properties, geometry, _ in records)
    result["origin"] = [layer for *_, layer in records]
    # The same facility is often mapped twice: a node and the outline of its grounds. Keep the node.
    if not result.empty:
        metric = result.to_crs(METRIC)
        metric["kind"] = [p["facility_type"] for p in metric["properties"]]
        nodes = metric[metric["origin"] == "points"]
        outlines = metric[metric["origin"] == "multipolygons"]
        drop: set[str] = set()
        if not nodes.empty and not outlines.empty:
            near = gpd.sjoin_nearest(
                outlines[["id", "kind", "geometry"]],
                nodes[["id", "kind", "geometry"]],
                how="inner",
                max_distance=150.0,
                distance_col="distance",
            )
            for item in near.itertuples():
                if item.kind_left == item.kind_right:
                    drop.add(str(item.id_left))
                    notes.append(
                        Note(
                            "transform.merged",
                            f"area-mapped {item.kind_left} dropped in favour of node {item.id_right} "
                            f"{float(item.distance):.0f} m away",
                            str(item.id_left),
                        )
                    )
        # Large sites (hospitals) are often mapped building by building, each tagged as the facility.
        remaining = outlines[~outlines["id"].isin(drop)].sort_values("id")
        kept_outlines: list[tuple[str, str, str, Any]] = []
        for item in remaining.itertuples():
            name = str(item.properties.get("name", "")).strip().lower()
            twin = next(
                (
                    other_id
                    for other_id, other_kind, other_name, other_geometry in kept_outlines
                    if other_kind == item.kind
                    and other_name == name
                    and other_geometry.distance(item.geometry) <= 150
                ),
                None,
            )
            if twin is None:
                kept_outlines.append((str(item.id), item.kind, name, item.geometry))
            else:
                drop.add(str(item.id))
                notes.append(
                    Note(
                        "transform.merged",
                        f"area-mapped {item.kind} dropped: part of the same site as {twin}",
                        str(item.id),
                    )
                )
        result = result[~result["id"].isin(drop)]
    return result.drop(columns=["origin"])


def _roads(staged: Path, dataset: DatasetConfig, area: BBox, notes: list[Note]) -> gpd.GeoDataFrame:
    if not dataset.classes:
        raise ProfileError(f"dataset {dataset.name}: list the highway types to keep (classes)")
    data = read_staged(staged, "lines", f"highway IN ({_quote(dataset.classes)})", area, LINE_COLUMNS)
    records = []
    for row in data.to_dict("records"):
        highway = _t(row, "highway")
        ref = _t(row, "ref")
        klass, basis = road_class(highway, ref)
        properties = {
            **_names(row),
            "road_class": klass,
            "ref_code": ref,
            "osm_highway": highway,
            "osm_road_class_basis": basis,
        }
        records.append((_element_id(row, "lines"), clean(properties), row["geometry"]))
    return frame(records)


def _water_lines(staged: Path, dataset: DatasetConfig, area: BBox, notes: list[Note]) -> gpd.GeoDataFrame:
    classes = dataset.classes or ["river", "canal", "stream"]
    unknown = sorted(set(classes) - {"river", "canal", "stream"})
    if unknown:
        raise ProfileError(f"dataset {dataset.name}: waterway classes must be river, canal or stream")
    data = read_staged(staged, "lines", f"waterway IN ({_quote(classes)})", area, LINE_COLUMNS)
    records = []
    for row in data.to_dict("records"):
        properties = {
            **_names(row),
            "water_type": _t(row, "waterway"),
            "osm_waterway": _t(row, "waterway"),
            "intermittent": _t(row, "intermittent") == "yes" or None,
        }
        records.append((_element_id(row, "lines"), clean(properties), row["geometry"]))
    return frame(records)


def _water_areas(staged: Path, dataset: DatasetConfig, area: BBox, notes: list[Note]) -> gpd.GeoDataFrame:
    classes = dataset.classes or ["reservoir", "tank", "lake", "lagoon", "wetland"]
    where = "\"natural\" IN ('water', 'wetland') OR landuse = 'reservoir' OR water IS NOT NULL"
    data = read_staged(staged, "multipolygons", where, area, AREA_COLUMNS)
    if data.empty:
        return frame([])
    areas = metric_area(data.geometry)
    records = []
    minimum = dataset.min_area_m2 or 0.0
    for row, size in zip(data.to_dict("records"), areas, strict=True):
        kind, basis = water_type(row)
        if kind not in classes or size < minimum:
            continue
        properties = {
            **_names(row),
            "water_type": kind,
            "osm_water_type_basis": basis,
            "osm_water": _t(row, "water"),
        }
        records.append((_element_id(row, "multipolygons"), clean(properties), row["geometry"]))
    return frame(records)


def _protected_areas(staged: Path, dataset: DatasetConfig, area: BBox, notes: list[Note]) -> gpd.GeoDataFrame:
    where = "boundary IN ('protected_area', 'national_park') OR leisure = 'nature_reserve'"
    data = read_staged(staged, "multipolygons", where, area, AREA_COLUMNS)
    minimum = dataset.min_area_m2 or 0.0
    sizes = metric_area(data.geometry) if not data.empty else pd.Series(dtype=float)
    records = []
    for row, size in zip(data.to_dict("records"), sizes, strict=True):
        identifier = _element_id(row, "multipolygons")
        columns = protected_area(row)
        if isinstance(columns, str):
            notes.append(Note("transform.skipped", f"protected area left out: {columns}", identifier))
            continue
        if size < minimum:
            notes.append(
                Note("transform.skipped", f"protected area smaller than {minimum:g} m² left out", identifier)
            )
            continue
        properties = {**_names(row), **columns}
        records.append((identifier, clean(properties), row["geometry"]))
    return frame(records)


THEMES: Final[Mapping[str, Callable[[Path, DatasetConfig, BBox, list[Note]], gpd.GeoDataFrame]]] = {
    "settlements": _settlements,
    "facilities": _facilities,
    "roads": _roads,
    "water_lines": _water_lines,
    "water_areas": _water_areas,
    "protected_areas": _protected_areas,
}
THEME_RULES: Final[Mapping[str, str]] = {
    "settlements": "place nodes; settlement_type from place (capital=yes -> capital); name from name:en or "
    "name",
    "facilities": "amenity/healthcare/office tag rules (app.pipeline.adapters.osm.facility_type); areas as "
    "a point "
    "on their surface, dropped when a node of the same type lies within 150 m or when they are another "
    "building "
    "of the same site (same type and name within 150 m)",
    "roads": "highway ways; road_class from the route number (ref), else motorway -> E, local roads -> "
    "local, "
    "track -> track, otherwise unknown",
    "water_lines": "waterway ways (river, canal, stream)",
    "water_areas": "natural=water/wetland and landuse=reservoir areas; tanks recognised by name (wewa, "
    "kulam, tank)",
    "protected_areas": "boundary=protected_area/national_park and leisure=nature_reserve areas with a name "
    "and a "
    "recognised designation; managing authority from the operator tag, else inferred from the designation",
}


def extract(
    context: BuildContext, dataset: DatasetConfig, source: SourceConfig, acquired: AcquiredSource
) -> Extracted:
    assert dataset.theme is not None  # checked by the profile
    staged = stage(context, acquired)
    area = context.profile.area(dataset.area)
    notes: list[Note] = []
    data = THEMES[dataset.theme](staged, dataset, area, notes)
    read = len(data) + sum(1 for note in notes if note.check == "transform.skipped")
    if dataset.select == "representative_point":
        data = select_area(data, area, "representative_point")
    transformation = (
        f"GDAL {gdal.version_string()} OSM driver (app/pipeline/osmconf.ini) to GeoPackage; "
        f"{THEME_RULES[dataset.theme]}"
        + (f"; classes {', '.join(dataset.classes)}" if dataset.classes else "")
        + (f"; minimum area {dataset.min_area_m2:g} m²" if dataset.min_area_m2 else "")
        + f"; area {dataset.area} {list(area)}; coordinates rounded to 1e-7 degrees"
    )
    return Extracted(
        frame=data,
        operation=choose_operation("EPSG:4326"),
        transformation=transformation,
        source_crs="EPSG:4326",
        read_count=read,
        verification={"points": 0, "note": "OpenStreetMap coordinates are WGS 84"},
        notes=notes,
    )
