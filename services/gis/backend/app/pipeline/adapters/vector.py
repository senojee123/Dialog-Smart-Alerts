"""The ``vector`` adapter: any GDAL vector source, mapped to a layer by a declared field mapping.

This is the adapter for agency data (Survey Department boundaries, DWC and Forest Department protected
areas, DMC/NBRO hazard zones, Ministry of Health facilities) as well as open datasets such as
geoBoundaries. Everything about the source is declared in the profile, nothing is inferred:

* ``input_layer``: the layer inside the file (GeoPackage, FileGDB); a single-layer file needs none;
* ``source_crs`` (on the source): required when the file does not state its CRS, and checked against it
  when it does; the coordinate operation to EPSG:4326 is chosen and verified by :mod:`app.pipeline.crs`;
* ``where``: an attribute filter applied by ogr2ogr;
* ``id_field``: the field holding a stable identifier (feature ids are what releases are compared by);
* ``fields``: target column <- source field; ``values``: value translation per target column;
  ``properties``: constants; ``keep_attributes``: source fields to keep in ``attributes``.

ogr2ogr stages the selected features in a GeoPackage in EPSG:4326 (applying the recorded operation with
``-ct``); GeoPandas does the mapping.
"""

from __future__ import annotations

from typing import Any

import pyogrio

from app.pipeline import gdal
from app.pipeline.acquire import AcquiredSource
from app.pipeline.adapters import BuildContext, Extracted, Note
from app.pipeline.crs import choose_operation, resolve_source_crs, verify_operation
from app.pipeline.errors import ProfileError
from app.pipeline.features import clean, frame, select_area, text
from app.pipeline.profile import DatasetConfig, SourceConfig


def _source_uri(acquired: AcquiredSource) -> str:
    path = str(acquired.path)
    if path.endswith(".zip"):
        return f"/vsizip/{path}"
    return path


def extract(
    context: BuildContext, dataset: DatasetConfig, source: SourceConfig, acquired: AcquiredSource
) -> Extracted:
    label = f"{dataset.name} ({source.code})"
    if dataset.id_field is None:
        raise ProfileError(
            f"dataset {dataset.name}: name the field with stable feature identifiers (id_field)",
            extensions={"dataset": dataset.name},
        )
    uri = _source_uri(acquired)
    layer = gdal.info(uri, open_options=source.open_options).layer(dataset.input_layer)
    wanted = {dataset.id_field, *dataset.fields.values(), *dataset.keep_attributes}
    missing = sorted(field for field in wanted if field not in layer.fields)
    if missing:
        raise ProfileError(
            f"dataset {dataset.name}: the source layer {layer.name} has no field(s) {', '.join(missing)}",
            extensions={"dataset": dataset.name, "fields": list(layer.fields)},
        )
    source_crs = resolve_source_crs(source.source_crs, layer.crs_wkt, label=label)
    operation = choose_operation(
        source_crs, pinned=source.coordinate_operation, allow_ballpark=source.allow_ballpark, label=label
    )
    sample: list[tuple[float, float]] = []
    if layer.extent is not None:
        x0, y0, x1, y1 = layer.extent
        sample = [(x0, y0), (x1, y1), ((x0 + x1) / 2, (y0 + y1) / 2)]
    verification = verify_operation(
        operation, sample, control_points=[point.point() for point in source.control_points], label=label
    )
    area = context.profile.area(dataset.area)
    staged = context.staging_dir / f"{dataset.name}.gpkg"
    gdal.translate(
        gdal.Translate(
            source=uri,
            destination=staged,
            destination_layer="data",
            source_layers=[layer.name],
            source_crs=source_crs,
            coordinate_operation=None if operation.pipeline is None else f"+{operation.pipeline}",
            spatial_filter=area,
            where=dataset.where,
            select=sorted(wanted),
            open_options=source.open_options,
        )
    )
    data = pyogrio.read_dataframe(staged, layer="data")
    read = len(data)
    data = select_area(data, area, dataset.select)
    notes: list[Note] = []
    records = []
    for values in data.to_dict("records"):
        identifier = text(values.get(dataset.id_field))
        properties: dict[str, Any] = dict(dataset.properties)
        for target, field_name in dataset.fields.items():
            value = values.get(field_name)
            if target in dataset.values:
                value = dataset.values[target].get(str(text(value)), value)
            properties[target] = text(value) if isinstance(value, str) else value
        for field_name in dataset.keep_attributes:
            properties[f"source_{field_name.lower()}"] = values.get(field_name)
        geometry = values["geometry"]
        # A feature without an identifier goes on to the file QA, which leaves it out and counts it
        # (identifier.missing, and the share of rejected features).
        feature = None if identifier is None else f"{dataset.id_prefix}{identifier}"
        records.append((feature, clean(properties), geometry))
    selection = "representative point" if dataset.select == "representative_point" else "intersection"
    transformation = (
        f"ogr2ogr (GDAL {gdal.version_string()}) from layer {layer.name} of {acquired.path.name}"
        + (f" where {dataset.where}" if dataset.where else "")
        + f"; {operation.lineage()}; area {dataset.area} {list(area)} by {selection}"
        + "; fields mapped by the profile; coordinates rounded to 1e-7 degrees"
    )
    return Extracted(
        frame=frame(records),
        operation=operation,
        transformation=transformation,
        source_crs=source_crs,
        read_count=read,
        verification=verification,
        notes=notes,
    )
