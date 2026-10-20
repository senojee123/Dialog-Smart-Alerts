"""The basemap of a release: vector tiles (PMTiles) from OpenStreetMap, a MapLibre style and glyphs.

Plan §8: in the MVP the basemap is one PMTiles file served as a static file and read by MapLibre with
HTTP range requests (the ``pmtiles://`` protocol the map client registers), so no tile server is needed.

Built from the release's sources, with the zoom levels at which each kind of feature appears::

    land        country outline (land source)                              z0+
    landcover   forest (national) z8+; farmland, orchards, residential (detail area) z11+
    protected   protected areas (national parks, sanctuaries, reserves), and their outlines   z6+
    water       lakes, reservoirs, tanks: >= 1 km2 z5+, >= 10 ha z8+, smaller (detail area) z11+
    waterway    rivers z8+; canals and streams (detail area) z12+
    boundaries  province (admin_level 4) z3+ and district (5) z7+ boundaries
    railway     z9+
    roads       motorway/trunk z5+, primary z7+, secondary z8+, tertiary z10+, local (detail area) z12+,
                tracks (detail area) z13+
    places      cities z5+, towns z8+, villages z11+ and hamlets z13+ (detail area)

GDAL writes the tiles (MVT in PMTiles, EPSG:3857). Labels use a Latin-script name (``name:en`` or
``name``): MapLibre cannot shape Sinhala or Tamil text, so those names are kept in the tiles
(``name_si``, ``name_ta``) for a future renderer but not drawn. Output (``data/basemap/<release>/``)::

    <name>.pmtiles, style.json, fonts/<font>/<range>.pbf, glyphs.json, artifacts.json

``artifacts.json`` describes the files for ``python -m app.pipeline artifacts``, which records them with
their sources and licences as artifacts of the (draft) release.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import geopandas as gpd
import pyogrio
import shapely

from app.pipeline import gdal
from app.pipeline.acquire import AcquiredSource, acquire, sha256_of
from app.pipeline.adapters import BuildContext
from app.pipeline.adapters.osm import (
    AREA_COLUMNS,
    LINE_COLUMNS,
    POINT_COLUMNS,
    protected_area,
    read_staged,
    stage,
    water_type,
)
from app.pipeline.artifacts import write_artifacts
from app.pipeline.build import tool_versions
from app.pipeline.errors import PipelineError, SourceError
from app.pipeline.features import latin_label, metric_area, text
from app.pipeline.profile import BasemapConfig, Profile, SourceConfig, check_licences, load_profile, raw_path
from app.schemas.reference_data import merge_attribution
from app.services.reference_releases import ArtifactSourceSpec, ArtifactSpec

logger = logging.getLogger(__name__)

TILE_CRS: Final = "EPSG:3857"
MAX_ZOOM_DEFAULT: Final = 14
MAX_PART_VERTICES: Final = 512
WATER_WHERE: Final = "\"natural\" IN ('water', 'wetland') OR landuse = 'reservoir' OR water IS NOT NULL"


@dataclass(frozen=True, slots=True)
class TileLayer:
    source_layer: str
    target: str
    min_zoom: int
    description: str


@dataclass(slots=True)
class BasemapResult:
    release_code: str
    directory: Path
    tiles: Path
    style: Path
    layers: dict[str, int] = field(default_factory=dict)
    artifacts: list[ArtifactSpec] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "release": self.release_code,
            "directory": str(self.directory),
            "tiles": self.tiles.name,
            "tilesBytes": self.tiles.stat().st_size,
            "style": self.style.name,
            "features": self.layers,
            "artifacts": [artifact.name for artifact in self.artifacts],
        }


def _gdf(frame: gpd.GeoDataFrame, columns: Mapping[str, list[Any]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(dict(columns), geometry=list(frame.geometry), crs=4326)


def subdivide(geometry: Any, max_vertices: int = MAX_PART_VERTICES) -> list[Any]:
    """Split a polygon into parts of at most ``max_vertices`` vertices by halving its box (like ST_Subdivide).

    Vector tiles clip every polygon to every tile it touches; the country outline or a national park with
    tens of thousands of vertices, clipped and quantised at low zoom, can come out as a ring the renderer
    cannot fill. Small parts clip cleanly, and adjacent parts of one fill show no seams.
    """
    if geometry is None or geometry.is_empty:
        return []
    if shapely.get_num_coordinates(geometry) <= max_vertices:
        return [part for part in shapely.get_parts(geometry) if not part.is_empty]
    x0, y0, x1, y1 = geometry.bounds
    if x1 - x0 >= y1 - y0:
        middle = (x0 + x1) / 2
        halves = (shapely.box(x0, y0, middle, y1), shapely.box(middle, y0, x1, y1))
    else:
        middle = (y0 + y1) / 2
        halves = (shapely.box(x0, y0, x1, middle), shapely.box(x0, middle, x1, y1))
    parts: list[Any] = []
    for half in halves:
        piece = shapely.make_valid(shapely.intersection(geometry, half))
        polygons = [
            item for item in shapely.get_parts(piece) if item.geom_type in ("Polygon", "MultiPolygon")
        ]
        for polygon in polygons:
            parts.extend(subdivide(polygon, max_vertices))
    return parts


def _subdivided(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Every polygon of a layer as parts of bounded size, keeping each part's attributes."""
    if frame.empty:
        return frame
    rows = []
    geometries = []
    attributes = frame.drop(columns="geometry").to_dict("records")
    for values, geometry in zip(attributes, frame.geometry, strict=True):
        valid = geometry if geometry.is_valid else shapely.make_valid(geometry)
        for part in subdivide(valid):
            rows.append(values)
            geometries.append(part)
    return gpd.GeoDataFrame(rows, geometry=geometries, crs=frame.crs)


def _layers(
    profile: Profile, config: BasemapConfig, staged: Path, land: AcquiredSource
) -> dict[str, tuple[TileLayer, gpd.GeoDataFrame]]:
    national = profile.area("national") if "national" in profile.areas else profile.area(config.detail_area)
    detail = profile.area(config.detail_area)
    layers: dict[str, tuple[TileLayer, gpd.GeoDataFrame]] = {}

    def add(layer: TileLayer, frame: gpd.GeoDataFrame) -> None:
        if frame.empty:
            return
        if frame.geom_type.isin(["Polygon", "MultiPolygon"]).all():
            frame = _subdivided(frame)
        layers[layer.source_layer] = (layer, frame)

    outline = pyogrio.read_dataframe(land.path)
    if outline.crs is None or outline.crs.to_epsg() != 4326:
        raise PipelineError("the basemap land source must be EPSG:4326")
    add(TileLayer("land", "land", 0, "country outline"), _gdf(outline, {"kind": ["land"] * len(outline)}))

    areas = read_staged(staged, "multipolygons", WATER_WHERE, national, AREA_COLUMNS)
    if not areas.empty:
        sizes = metric_area(areas.geometry)
        water_kinds = [water_type(row)[0] for row in areas.to_dict("records")]
        areas = areas.assign(kind=water_kinds, size=list(sizes))
        in_detail = areas.geometry.intersects(shapely.box(*detail))
        bands = (
            ("water_large", areas["size"] >= 1_000_000, 5),
            ("water_medium", (areas["size"] >= 100_000) & (areas["size"] < 1_000_000), 8),
            ("water_small", (areas["size"] >= 1_000) & (areas["size"] < 100_000) & in_detail, 11),
        )
        for name, selector, zoom in bands:
            part = areas[selector]
            add(
                TileLayer(name, "water", zoom, "lakes, reservoirs, tanks, lagoons, wetlands"),
                _gdf(
                    part,
                    {
                        "kind": list(part["kind"]),
                        "label": [
                            latin_label(r.get("name_en"), r.get("name")) for r in part.to_dict("records")
                        ],
                    },
                ),
            )

    cover = read_staged(
        staged,
        "multipolygons",
        "\"natural\" = 'wood' OR landuse IN ('forest', 'farmland', 'orchard', 'meadow', 'residential')",
        national,
        AREA_COLUMNS,
    )
    if not cover.empty:
        kind = cover["landuse"].fillna(cover["natural"]).replace({"wood": "forest"})
        cover = cover.assign(kind=kind)
        forest = cover[cover["kind"] == "forest"]
        add(
            TileLayer("landcover_forest", "landcover", 8, "forest and woodland"),
            _gdf(forest, {"kind": list(forest["kind"])}),
        )
        other = cover[(cover["kind"] != "forest") & cover.geometry.intersects(shapely.box(*detail))]
        add(
            TileLayer("landcover_detail", "landcover", 11, "farmland, orchards, meadows, residential"),
            _gdf(other, {"kind": list(other["kind"])}),
        )

    parks = read_staged(
        staged,
        "multipolygons",
        "boundary IN ('protected_area', 'national_park') OR leisure = 'nature_reserve'",
        national,
        AREA_COLUMNS,
    )
    park_rows = [(row, protected_area(row)) for row in parks.to_dict("records")]
    kept = [(row, columns) for row, columns in park_rows if isinstance(columns, dict)]
    if kept:
        frame = gpd.GeoDataFrame(
            {
                "kind": [columns["designation"] for _, columns in kept],
                "label": [latin_label(columns["name"]) for _, columns in kept],
            },
            geometry=[row["geometry"] for row, _ in kept],
            crs=4326,
        )
        add(TileLayer("protected", "protected", 6, "national parks, sanctuaries, reserves"), frame)
        # Outlines as lines of their own: the filled polygons are split into parts for tiling.
        add(
            TileLayer("protected_outline", "protected_outline", 6, "outlines of protected areas"),
            gpd.GeoDataFrame({"kind": list(frame["kind"])}, geometry=list(frame.geometry.boundary), crs=4326),
        )

    lines = read_staged(staged, "lines", "waterway IN ('river', 'canal', 'stream')", national, LINE_COLUMNS)
    rivers = lines[lines["waterway"] == "river"]
    add(
        TileLayer("waterway_river", "waterway", 8, "rivers"),
        _gdf(
            rivers,
            {
                "kind": list(rivers["waterway"]),
                "label": [latin_label(r.get("name_en"), r.get("name")) for r in rivers.to_dict("records")],
            },
        ),
    )
    minor = lines[(lines["waterway"] != "river") & lines.geometry.intersects(shapely.box(*detail))]
    add(
        TileLayer("waterway_minor", "waterway", 12, "canals and streams"),
        _gdf(minor, {"kind": list(minor["waterway"])}),
    )

    admin = read_staged(
        staged,
        "multipolygons",
        "boundary = 'administrative' AND admin_level IN ('4', '5')",
        national,
        ["admin_level", "name"],
    )
    if not admin.empty:
        admin = admin.assign(geometry=admin.geometry.boundary)
        for level, zoom in (("4", 3), ("5", 7)):
            part = admin[admin["admin_level"] == level]
            add(
                TileLayer(f"boundaries_{level}", "boundaries", zoom, f"admin_level {level} boundaries"),
                _gdf(part, {"admin_level": [int(level)] * len(part)}),
            )

    rail = read_staged(staged, "lines", "railway = 'rail'", national, ["railway"])
    add(TileLayer("railway", "railway", 9, "railways"), _gdf(rail, {"kind": ["rail"] * len(rail)}))

    roads = read_staged(staged, "lines", "highway IS NOT NULL", national, LINE_COLUMNS)
    highway = roads["highway"].fillna("")
    road_bands: tuple[tuple[str, tuple[str, ...], int, bool], ...] = (
        ("roads_trunk", ("motorway", "motorway_link", "trunk", "trunk_link"), 5, False),
        ("roads_primary", ("primary", "primary_link"), 7, False),
        ("roads_secondary", ("secondary", "secondary_link"), 8, False),
        ("roads_tertiary", ("tertiary", "tertiary_link"), 10, False),
        ("roads_minor", ("unclassified", "residential", "living_street", "service", "road"), 12, True),
        ("roads_track", ("track",), 13, True),
    )
    for name, kinds, zoom, detail_only in road_bands:
        selector = highway.isin(kinds)
        if detail_only:
            selector &= roads.geometry.intersects(shapely.box(*detail))
        part = roads[selector]
        add(
            TileLayer(name, "roads", zoom, ", ".join(kinds)),
            _gdf(
                part,
                {
                    "kind": [value.replace("_link", "") for value in part["highway"]],
                    "link": [value.endswith("_link") for value in part["highway"]],
                    "ref": [text(value) for value in part["ref"]],
                    "label": [latin_label(r.get("name_en"), r.get("name")) for r in part.to_dict("records")],
                },
            ),
        )

    places = read_staged(
        staged, "points", "place IN ('city', 'town', 'village', 'hamlet')", national, POINT_COLUMNS
    )
    for kind, zoom, detail_only in (
        ("city", 5, False),
        ("town", 8, False),
        ("village", 11, True),
        ("hamlet", 13, True),
    ):
        selector = places["place"] == kind
        if detail_only:
            selector &= places.geometry.within(shapely.box(*detail))
        part = places[selector]
        labels = [latin_label(r.get("name_en"), r.get("name")) for r in part.to_dict("records")]
        add(
            TileLayer(f"places_{kind}", "places", zoom, f"{kind} labels"),
            _gdf(
                part,
                {
                    "kind": [kind] * len(part),
                    "label": labels,
                    "name_si": [text(value) for value in part["name_si"]],
                    "name_ta": [text(value) for value in part["name_ta"]],
                    "population": [text(value) for value in part["population"]],
                },
            ),
        )
    return layers


def _style(config: BasemapConfig, release: str, attribution: str) -> dict[str, Any]:
    base = f"{config.public_path.rstrip('/')}/{release}"
    font = [config.font]

    def road(kind: str, colour: str, widths: list[float], min_zoom: int) -> list[dict[str, Any]]:
        def width_for(extra: float) -> list[Any]:
            return [
                "interpolate",
                ["exponential", 1.5],
                ["zoom"],
                min_zoom,
                widths[0] + extra,
                14,
                widths[1] + extra,
                18,
                widths[2] + extra,
            ]

        width = width_for(0.0)
        return [
            {
                "id": f"road-{kind}-casing",
                "type": "line",
                "source": "basemap",
                "source-layer": "roads",
                "minzoom": min_zoom,
                "filter": ["==", ["get", "kind"], kind],
                "layout": {"line-cap": "round", "line-join": "round"},
                "paint": {"line-color": "#c9c3b8", "line-width": width_for(1.2)},
            },
            {
                "id": f"road-{kind}",
                "type": "line",
                "source": "basemap",
                "source-layer": "roads",
                "minzoom": min_zoom,
                "filter": ["==", ["get", "kind"], kind],
                "layout": {"line-cap": "round", "line-join": "round"},
                "paint": {"line-color": colour, "line-width": width},
            },
        ]

    landcover_colours = [
        "match",
        ["get", "kind"],
        "forest",
        "#d4e5c4",
        "farmland",
        "#eef0da",
        "orchard",
        "#e2ecd0",
        "meadow",
        "#e6efd6",
        "residential",
        "#e8e4de",
        "#eeeeee",
    ]
    layers: list[dict[str, Any]] = [
        {"id": "background", "type": "background", "paint": {"background-color": "#bcd6e8"}},
        {
            "id": "land",
            "type": "fill",
            "source": "basemap",
            "source-layer": "land",
            "paint": {"fill-color": "#f5f2eb"},
        },
        {
            "id": "landcover",
            "type": "fill",
            "source": "basemap",
            "source-layer": "landcover",
            "paint": {"fill-color": landcover_colours, "fill-opacity": 0.9},
        },
        {
            "id": "protected-fill",
            "type": "fill",
            "source": "basemap",
            "source-layer": "protected",
            "paint": {"fill-color": "#b9d7a1", "fill-opacity": 0.3, "fill-antialias": False},
        },
        {
            "id": "protected-outline",
            "type": "line",
            "source": "basemap",
            "source-layer": "protected_outline",
            "paint": {"line-color": "#6b9a52", "line-width": 1, "line-dasharray": [3, 2]},
        },
        {
            "id": "water",
            "type": "fill",
            "source": "basemap",
            "source-layer": "water",
            "paint": {"fill-color": "#aacde3"},
        },
        {
            "id": "waterway",
            "type": "line",
            "source": "basemap",
            "source-layer": "waterway",
            "paint": {
                "line-color": "#9cc3dd",
                "line-width": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    8,
                    0.6,
                    14,
                    ["match", ["get", "kind"], "river", 3, 1.2],
                ],
            },
        },
        {
            "id": "boundaries",
            "type": "line",
            "source": "basemap",
            "source-layer": "boundaries",
            "paint": {
                "line-color": "#a497ae",
                "line-dasharray": [4, 2],
                "line-width": ["match", ["get", "admin_level"], 4, 1.4, 0.8],
            },
        },
        {
            "id": "railway",
            "type": "line",
            "source": "basemap",
            "source-layer": "railway",
            "paint": {"line-color": "#9a9a9a", "line-width": 1.2, "line-dasharray": [2, 2]},
        },
        *road("track", "#f6f4ef", [0.4, 1.2, 4], 13),
        *road("minor", "#ffffff", [0.6, 2.5, 10], 12),
        *road("residential", "#ffffff", [0.6, 2.5, 10], 12),
        *road("unclassified", "#ffffff", [0.6, 2.5, 10], 12),
        *road("living_street", "#ffffff", [0.6, 2.5, 10], 12),
        *road("service", "#ffffff", [0.4, 1.5, 6], 12),
        *road("tertiary", "#fffbe8", [0.8, 3.5, 14], 10),
        *road("secondary", "#fdf1c7", [1, 4.5, 18], 8),
        *road("primary", "#fbdc9f", [1.2, 5.5, 22], 5),
        *road("trunk", "#f9c77e", [1.4, 6, 24], 5),
        *road("motorway", "#f3a86b", [1.6, 6.5, 26], 5),
        {
            "id": "road-labels",
            "type": "symbol",
            "source": "basemap",
            "source-layer": "roads",
            "minzoom": 13,
            "filter": ["has", "label"],
            "layout": {
                "symbol-placement": "line",
                "text-field": ["get", "label"],
                "text-font": font,
                "text-size": 11,
            },
            "paint": {"text-color": "#555555", "text-halo-color": "#ffffff", "text-halo-width": 1.2},
        },
        {
            "id": "place-labels",
            "type": "symbol",
            "source": "basemap",
            "source-layer": "places",
            "filter": ["has", "label"],
            "layout": {
                "text-field": ["get", "label"],
                "text-font": font,
                "text-size": ["match", ["get", "kind"], "city", 15, "town", 13, "village", 11, 10],
                "symbol-sort-key": ["match", ["get", "kind"], "city", 1, "town", 2, "village", 3, 4],
            },
            "paint": {"text-color": "#333333", "text-halo-color": "#ffffff", "text-halo-width": 1.5},
        },
    ]
    return {
        "version": 8,
        "name": f"GIS Core basemap ({release})",
        "metadata": {"gis:refDataRelease": release, "gis:generator": "app.pipeline.basemap"},
        "glyphs": f"{base}/fonts/{{fontstack}}/{{range}}.pbf",
        "sources": {
            "basemap": {
                "type": "vector",
                "url": f"pmtiles://{base}/{config.name}.pmtiles",
                "attribution": attribution,
            }
        },
        "layers": layers,
    }


def _fetch_glyphs(
    source: SourceConfig,
    config: BasemapConfig,
    raw_dir: Path,
    profile: Profile,
    target: Path,
    allow_download: bool,
) -> dict[str, str]:
    """Glyph ranges for the label font: from the raw directory, or downloaded (https) into it."""
    if source.download is None:
        raise SourceError(f"source {source.code}: the glyph source needs a download URL template")
    directory = raw_path(raw_dir, source, profile.directory) / config.font
    checksums: dict[str, str] = {}
    for glyph_range in config.glyph_ranges:
        local = directory / f"{glyph_range}.pbf"
        if not local.exists():
            if not allow_download:
                raise SourceError(f"glyphs {local} are missing and downloads are not allowed")
            url = source.download.format(fontstack=urllib.parse.quote(config.font), range=glyph_range)
            from app.pipeline.acquire import _download

            header = os.environ.get(source.auth_header_env) if source.auth_header_env else None
            _download(url, local, header)
        destination = target / "fonts" / config.font / local.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, destination)
        checksums[f"fonts/{config.font}/{local.name}"] = sha256_of(destination)
    return checksums


def build_basemap(
    profile_path: Path,
    *,
    release_code: str,
    raw_dir: Path,
    output_root: Path,
    staging_dir: Path,
    allow_download: bool = True,
) -> BasemapResult:
    profile = load_profile(profile_path)
    if profile.basemap is None:
        raise PipelineError(f"profile {profile.profile.name} defines no basemap")
    check_licences(profile)
    config = profile.basemap
    target = output_root / release_code
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    context = BuildContext(profile=profile, raw_dir=raw_dir, staging_dir=staging_dir)
    osm_source = profile.sources[config.osm_source]
    land_source = profile.sources[config.land_source]
    osm = acquire(osm_source, raw_dir, profile_dir=profile.directory, allow_download=allow_download)
    land = acquire(land_source, raw_dir, profile_dir=profile.directory, allow_download=allow_download)
    staged = stage(context, osm)

    layers = _layers(profile, config, staged, land)
    package = staging_dir / f"basemap-{release_code}.gpkg"
    package.unlink(missing_ok=True)
    for name, (_, frame) in layers.items():
        pyogrio.write_dataframe(frame, package, layer=name, driver="GPKG", append=package.exists())
    conf = {
        name: {
            "target_name": layer.target,
            "description": layer.description,
            "minzoom": layer.min_zoom,
            "maxzoom": config.max_zoom,
        }
        for name, (layer, _) in layers.items()
    }
    tiles = target / f"{config.name}.pmtiles"
    gdal.write_pmtiles(
        package,
        tiles,
        layer_config=conf,
        min_zoom=config.min_zoom,
        max_zoom=config.max_zoom,
        name=f"GIS Core basemap {release_code}",
        description=f"OpenStreetMap basemap for reference data release {release_code}",
    )
    attribution = " · ".join(merge_attribution([osm_source.attribution, land_source.attribution]))
    style = _style(config, release_code, attribution)
    style_path = target / "style.json"
    style_path.write_text(json.dumps(style, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    glyph_source = profile.sources[config.glyphs_source] if config.glyphs_source else None
    glyphs: dict[str, str] = {}
    if glyph_source is not None:
        glyphs = _fetch_glyphs(glyph_source, config, raw_dir, profile, target, allow_download)
    glyph_index = target / "glyphs.json"
    glyph_index.write_text(
        json.dumps({"font": config.font, "files": glyphs}, indent=1) + "\n", encoding="utf-8"
    )

    versions = tool_versions()
    detail = profile.area(config.detail_area)
    bounds = tuple(float(value) for value in layers["land"][1].total_bounds) if "land" in layers else None
    osm_ref = ArtifactSourceSpec(
        osm_source.code,
        "roads, water, landcover, protected areas, boundaries, railways, places",
        osm.reference,
        osm.version,
        osm.sha256,
        osm.retrieved_at,
    )
    land_ref = ArtifactSourceSpec(
        land_source.code,
        "land (country outline)",
        land.reference,
        land.version,
        land.sha256,
        land.retrieved_at,
    )
    public = f"{config.public_path.rstrip('/')}/{release_code}"
    artifacts = [
        ArtifactSpec(
            kind="basemap_tiles",
            name=tiles.name,
            uri=f"{public}/{tiles.name}",
            media_type="application/vnd.pmtiles",
            sha256=sha256_of(tiles),
            size_bytes=tiles.stat().st_size,
            crs=TILE_CRS,
            transformation=f"GDAL {gdal.version_string()} PMTiles/MVT writer from a GeoPackage of OSM "
            "layers (EPSG:4326 to "
            f"EPSG:3857); detail layers only in area {config.detail_area} {list(detail)}",
            sources=[osm_ref, land_ref],
            min_zoom=config.min_zoom,
            max_zoom=config.max_zoom,
            bounds=bounds,  # type: ignore[arg-type]
            geometry_types=sorted(
                {str(t).upper() for _, frame in layers.values() for t in frame.geom_type.unique()}
            ),
            geometry_accuracy_m=20.0,
            metadata={
                "layers": {
                    name: {"target": layer.target, "minZoom": layer.min_zoom, "features": len(frame)}
                    for name, (layer, frame) in layers.items()
                }
            },
            tool_versions=versions,
        ),
        ArtifactSpec(
            kind="basemap_style",
            name="style.json",
            uri=f"{public}/style.json",
            media_type="application/json",
            sha256=sha256_of(style_path),
            size_bytes=style_path.stat().st_size,
            crs=TILE_CRS,
            transformation="MapLibre style generated by app.pipeline.basemap",
            sources=[osm_ref, land_ref],
            min_zoom=config.min_zoom,
            max_zoom=config.max_zoom,
            metadata={"layers": [layer["id"] for layer in style["layers"]]},
            tool_versions=versions,
        ),
    ]
    if glyph_source is not None:
        artifacts.append(
            ArtifactSpec(
                kind="basemap_glyphs",
                name="glyphs.json",
                uri=f"{public}/fonts/",
                media_type="application/x-protobuf",
                sha256=sha256_of(glyph_index),
                size_bytes=sum((target / name).stat().st_size for name in glyphs),
                crs=TILE_CRS,
                transformation=f"copied from {glyph_source.name}",
                sources=[
                    ArtifactSourceSpec(
                        glyph_source.code,
                        "label glyphs",
                        glyph_source.download or glyph_source.url or "",
                        glyph_source.version,
                    )
                ],
                metadata={"font": config.font, "files": glyphs},
                tool_versions=versions,
            )
        )
    write_artifacts(target / "artifacts.json", artifacts)
    package.unlink(missing_ok=True)
    logger.info("basemap built", extra={"release": release_code, "bytes": tiles.stat().st_size})
    return BasemapResult(
        release_code=release_code,
        directory=target,
        tiles=tiles,
        style=style_path,
        layers={name: len(frame) for name, (_, frame) in layers.items()},
        artifacts=artifacts,
    )
