"""Event locations and geo-context rows (schema ``geo``, row-level security by tenant).

Every statement runs in a transaction whose tenant is set (``app.db.session.transaction``); rows are
written for, and read from, that tenant only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB, UUID
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Integer, Text

from app.core.errors import GisError
from app.repositories.pg_errors import (
    CHECK_VIOLATION,
    driver_error,
    server_message,
    sqlstate,
    violated_constraint,
)
from app.schemas.geo_context import GeometryKind, LocationSource, Relation, ZoneType

TENANT_FOREIGN_KEY = "fk_event_location_tenant_id_tenant"

__all__ = [
    "EventPartitionMissingError",
    "EventRepository",
    "UnknownTenantError",
    "is_missing_partition",
    "violated_constraint",
]


class EventPartitionMissingError(GisError):
    """The monthly partition for ``observed_at`` does not exist yet (see ``geo.ensure_event_partition``)."""

    status_code = 503
    code = "event_partition_missing"
    title = "Event storage for this month is not prepared"


class UnknownTenantError(GisError):
    """The tenant is not registered in ``meta.tenant``."""

    status_code = 403
    code = "tenant_not_registered"
    title = "Tenant is not registered with the GIS service"


def is_missing_partition(error: DBAPIError) -> bool:
    """True for PostgreSQL's "no partition of relation ... found for row" (SQLSTATE 23514, no constraint)."""
    constraint = getattr(driver_error(error), "constraint_name", None)
    return (
        sqlstate(error) == CHECK_VIOLATION
        and constraint is None
        and "no partition of relation" in server_message(error)
    )


@dataclass(frozen=True, slots=True)
class EventLocationRecord:
    event_id: str
    observed_at: datetime
    event_type: str
    event_subtype: str | None
    source_type: str
    device_id: uuid.UUID | None
    source_ref: str | None
    location_source: str
    geometry_wkb: bytes
    location_accuracy_m: float | None
    field_of_view_id: uuid.UUID | None
    field_of_view_wkb: bytes | None
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoredEventLocation:
    tenant_id: str
    event_id: str
    observed_at: datetime
    event_type: str
    location_source: LocationSource
    geometry_kind: GeometryKind
    geometry_wkb: bytes
    device_id: uuid.UUID | None
    field_of_view_id: uuid.UUID | None
    location_accuracy_m: float | None


@dataclass(frozen=True, slots=True)
class GeoContextRecord:
    event_id: str
    observed_at: datetime
    schema_version: str
    release_id: uuid.UUID
    release_code: str
    computed_at: datetime
    location_source: LocationSource
    admin_ids: tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]
    admin_codes: tuple[str | None, str | None, str | None, str | None]
    nearest_settlement_id: uuid.UUID | None
    nearest_settlement_distance_m: float | None
    nearest_road_id: uuid.UUID | None
    nearest_road_distance_m: float | None
    document: dict[str, Any]
    zone_hits: tuple[tuple[ZoneType, uuid.UUID, Relation], ...]
    geofence_hits: tuple[tuple[uuid.UUID, str, int, Relation], ...]


# Re-sending an event replaces its location; the stored context described the old location and is
# deleted in the same statement (its hits follow by ON DELETE CASCADE).
_UPSERT_LOCATION = text(
    """
    WITH upserted AS (
        INSERT INTO geo.event_location (
            event_id, observed_at, event_type, event_subtype, source_type, device_id, source_ref,
            location_source, geom, location_accuracy_m, field_of_view_id, field_of_view, attributes
        ) VALUES (
            :event_id, :observed_at, :event_type, :event_subtype, :source_type, :device_id, :source_ref,
            :location_source, public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326), :location_accuracy_m,
            :field_of_view_id,
            public.ST_Multi(public.ST_GeomFromWKB(CAST(:fov_wkb AS bytea), 4326)),
            :attributes
        )
        ON CONFLICT (tenant_id, event_id, observed_at) DO UPDATE SET
            event_type = EXCLUDED.event_type,
            event_subtype = EXCLUDED.event_subtype,
            source_type = EXCLUDED.source_type,
            device_id = EXCLUDED.device_id,
            source_ref = EXCLUDED.source_ref,
            location_source = EXCLUDED.location_source,
            geom = EXCLUDED.geom,
            location_accuracy_m = EXCLUDED.location_accuracy_m,
            field_of_view_id = EXCLUDED.field_of_view_id,
            field_of_view = EXCLUDED.field_of_view,
            attributes = EXCLUDED.attributes
        RETURNING tenant_id, event_id, observed_at, geometry_kind
    ),
    stale AS (
        DELETE FROM geo.event_geo_context AS c
        USING upserted AS u
        WHERE c.tenant_id = u.tenant_id AND c.event_id = u.event_id AND c.observed_at = u.observed_at
        RETURNING c.event_id
    )
    SELECT u.tenant_id, u.geometry_kind, (SELECT count(*) FROM stale) AS discarded_contexts
    FROM upserted AS u
    """
).bindparams(
    bindparam("device_id", type_=UUID),
    bindparam("field_of_view_id", type_=UUID),
    bindparam("wkb", type_=BYTEA),
    bindparam("fov_wkb", type_=BYTEA),
    bindparam("attributes", type_=JSONB),
)

_GET_LOCATION = text(
    """
    SELECT tenant_id, event_id, observed_at, event_type, location_source, geometry_kind,
           public.ST_AsBinary(geom) AS wkb, device_id, field_of_view_id, location_accuracy_m
    FROM geo.event_location
    WHERE tenant_id = meta.current_tenant_id() AND event_id = :event_id AND observed_at = :observed_at
    """
)

# The context row and its hits in one statement: the hits' foreign key to the context row is checked at
# the end of the statement, when the row exists. Everything is an upsert, and hits that the new result no
# longer has are deleted, so two concurrent enrichments of the same event cannot collide (at-least-once
# delivery) and the stored result always matches the document.
_INSERT_CONTEXT = text(
    """
    WITH new_zones AS (
        SELECT z.kind, z.id, z.relation
        FROM unnest(
            CAST(:zone_kinds AS text[]), CAST(:zone_ids AS uuid[]), CAST(:zone_relations AS text[])
        ) AS z(kind, id, relation)
    ),
    new_fences AS (
        SELECT f.id, f.owner, f.version, f.relation
        FROM unnest(
            CAST(:geofence_ids AS uuid[]), CAST(:geofence_tenants AS text[]),
            CAST(:geofence_versions AS integer[]), CAST(:geofence_relations AS text[])
        ) AS f(id, owner, version, relation)
    ),
    ctx AS (
        INSERT INTO geo.event_geo_context (
            tenant_id, event_id, observed_at, schema_version, release_id, release_code, computed_at,
            location_source, admin_l1_id, admin_l1_code, admin_l2_id, admin_l2_code, admin_l3_id,
            admin_l3_code, admin_l4_id, admin_l4_code, nearest_settlement_id, nearest_settlement_distance_m,
            nearest_road_id, nearest_road_distance_m, document
        ) VALUES (
            meta.current_tenant_id(), :event_id, :observed_at, :schema_version, :release_id, :release_code,
            :computed_at, :location_source, :l1_id, :l1_code, :l2_id, :l2_code, :l3_id, :l3_code, :l4_id,
            :l4_code, :settlement_id, :settlement_distance_m, :road_id, :road_distance_m, :document
        )
        ON CONFLICT (tenant_id, event_id, observed_at) DO UPDATE SET
            schema_version = EXCLUDED.schema_version,
            release_id = EXCLUDED.release_id,
            release_code = EXCLUDED.release_code,
            computed_at = EXCLUDED.computed_at,
            location_source = EXCLUDED.location_source,
            admin_l1_id = EXCLUDED.admin_l1_id,
            admin_l1_code = EXCLUDED.admin_l1_code,
            admin_l2_id = EXCLUDED.admin_l2_id,
            admin_l2_code = EXCLUDED.admin_l2_code,
            admin_l3_id = EXCLUDED.admin_l3_id,
            admin_l3_code = EXCLUDED.admin_l3_code,
            admin_l4_id = EXCLUDED.admin_l4_id,
            admin_l4_code = EXCLUDED.admin_l4_code,
            nearest_settlement_id = EXCLUDED.nearest_settlement_id,
            nearest_settlement_distance_m = EXCLUDED.nearest_settlement_distance_m,
            nearest_road_id = EXCLUDED.nearest_road_id,
            nearest_road_distance_m = EXCLUDED.nearest_road_distance_m,
            document = EXCLUDED.document
        RETURNING tenant_id, event_id, observed_at
    ),
    stale_zones AS (
        DELETE FROM geo.event_zone_hit AS h
        USING ctx
        WHERE h.tenant_id = ctx.tenant_id AND h.event_id = ctx.event_id AND h.observed_at = ctx.observed_at
          AND NOT EXISTS (
              SELECT 1 FROM new_zones AS z WHERE z.kind = h.zone_kind AND z.id = h.zone_id
          )
        RETURNING h.zone_id
    ),
    stale_fences AS (
        DELETE FROM geo.event_geofence_hit AS h
        USING ctx
        WHERE h.tenant_id = ctx.tenant_id AND h.event_id = ctx.event_id AND h.observed_at = ctx.observed_at
          AND NOT EXISTS (SELECT 1 FROM new_fences AS f WHERE f.id = h.geofence_id)
        RETURNING h.geofence_id
    ),
    zone_hits AS (
        INSERT INTO geo.event_zone_hit (tenant_id, event_id, observed_at, zone_kind, zone_id, relation)
        SELECT ctx.tenant_id, ctx.event_id, ctx.observed_at, z.kind, z.id, z.relation
        FROM ctx, new_zones AS z
        ON CONFLICT (tenant_id, event_id, observed_at, zone_kind, zone_id) DO UPDATE SET
            relation = EXCLUDED.relation
        RETURNING zone_id
    ),
    geofence_hits AS (
        INSERT INTO geo.event_geofence_hit (
            tenant_id, event_id, observed_at, geofence_id, geofence_tenant_id, geofence_version, relation
        )
        SELECT ctx.tenant_id, ctx.event_id, ctx.observed_at, f.id, f.owner, f.version, f.relation
        FROM ctx, new_fences AS f
        ON CONFLICT (tenant_id, event_id, observed_at, geofence_id) DO UPDATE SET
            geofence_tenant_id = EXCLUDED.geofence_tenant_id,
            geofence_version = EXCLUDED.geofence_version,
            relation = EXCLUDED.relation
        RETURNING geofence_id
    )
    SELECT (SELECT count(*) FROM zone_hits) AS zone_hits,
           (SELECT count(*) FROM geofence_hits) AS geofence_hits,
           (SELECT count(*) FROM stale_zones) + (SELECT count(*) FROM stale_fences) AS removed_hits
    """
).bindparams(
    bindparam("release_id", type_=UUID),
    bindparam("l1_id", type_=UUID),
    bindparam("l2_id", type_=UUID),
    bindparam("l3_id", type_=UUID),
    bindparam("l4_id", type_=UUID),
    bindparam("settlement_id", type_=UUID),
    bindparam("road_id", type_=UUID),
    bindparam("document", type_=JSONB),
    bindparam("zone_kinds", type_=ARRAY(Text)),
    bindparam("zone_ids", type_=ARRAY(UUID)),
    bindparam("zone_relations", type_=ARRAY(Text)),
    bindparam("geofence_ids", type_=ARRAY(UUID)),
    bindparam("geofence_tenants", type_=ARRAY(Text)),
    bindparam("geofence_versions", type_=ARRAY(Integer)),
    bindparam("geofence_relations", type_=ARRAY(Text)),
)

_GET_CONTEXT = text(
    """
    SELECT document FROM geo.event_geo_context
    WHERE tenant_id = meta.current_tenant_id() AND event_id = :event_id AND observed_at = :observed_at
    """
)

_ENSURE_PARTITION = text("SELECT geo.ensure_event_partition(:observed_at)")


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_partition(self, observed_at: datetime) -> str:
        return str(
            (await self._session.execute(_ENSURE_PARTITION, {"observed_at": observed_at})).scalar_one()
        )

    async def upsert_location(self, record: EventLocationRecord) -> tuple[str, GeometryKind]:
        """Insert or replace the location of an event; returns the owning tenant and the geometry kind.

        A stored geo-context of the event is deleted in the same statement: it described the previous
        location and must be recomputed. Raises :class:`EventPartitionMissingError` when the month is not
        prepared and :class:`UnknownTenantError` when the tenant is not registered; the transaction is then
        unusable and must be rolled back.
        """
        params = {
            "event_id": record.event_id,
            "observed_at": record.observed_at,
            "event_type": record.event_type,
            "event_subtype": record.event_subtype,
            "source_type": record.source_type,
            "device_id": record.device_id,
            "source_ref": record.source_ref,
            "location_source": record.location_source,
            "wkb": record.geometry_wkb,
            "location_accuracy_m": record.location_accuracy_m,
            "field_of_view_id": record.field_of_view_id,
            "fov_wkb": record.field_of_view_wkb,
            "attributes": record.attributes,
        }
        try:
            row = (await self._session.execute(_UPSERT_LOCATION, params)).one()
        except DBAPIError as exc:
            if is_missing_partition(exc):
                raise EventPartitionMissingError(
                    f"no event partition for {record.observed_at.isoformat()}",
                    extensions={"observedAt": record.observed_at.isoformat()},
                ) from exc
            if violated_constraint(exc) == TENANT_FOREIGN_KEY:
                raise UnknownTenantError(
                    "the tenant is not registered with the GIS service; ask an administrator to add it"
                ) from exc
            raise
        kind: GeometryKind = row.geometry_kind
        return str(row.tenant_id), kind

    async def get_location(self, event_id: str, observed_at: datetime) -> StoredEventLocation | None:
        row = (
            await self._session.execute(_GET_LOCATION, {"event_id": event_id, "observed_at": observed_at})
        ).one_or_none()
        if row is None:
            return None
        return StoredEventLocation(
            tenant_id=row.tenant_id,
            event_id=row.event_id,
            observed_at=row.observed_at,
            event_type=row.event_type,
            location_source=row.location_source,
            geometry_kind=row.geometry_kind,
            geometry_wkb=bytes(row.wkb),
            device_id=row.device_id,
            field_of_view_id=row.field_of_view_id,
            location_accuracy_m=None if row.location_accuracy_m is None else float(row.location_accuracy_m),
        )

    async def store_geo_context(self, record: GeoContextRecord) -> None:
        """Store the context of an event and its hits, replacing an earlier result (one statement)."""
        l1, l2, l3, l4 = record.admin_ids
        c1, c2, c3, c4 = record.admin_codes
        row = (
            await self._session.execute(
                _INSERT_CONTEXT,
                {
                    "event_id": record.event_id,
                    "observed_at": record.observed_at,
                    "schema_version": record.schema_version,
                    "release_id": record.release_id,
                    "release_code": record.release_code,
                    "computed_at": record.computed_at,
                    "location_source": record.location_source,
                    "l1_id": l1,
                    "l1_code": c1,
                    "l2_id": l2,
                    "l2_code": c2,
                    "l3_id": l3,
                    "l3_code": c3,
                    "l4_id": l4,
                    "l4_code": c4,
                    "settlement_id": record.nearest_settlement_id,
                    "settlement_distance_m": record.nearest_settlement_distance_m,
                    "road_id": record.nearest_road_id,
                    "road_distance_m": record.nearest_road_distance_m,
                    "document": record.document,
                    "zone_kinds": [kind for kind, _, _ in record.zone_hits],
                    "zone_ids": [zone_id for _, zone_id, _ in record.zone_hits],
                    "zone_relations": [relation for _, _, relation in record.zone_hits],
                    "geofence_ids": [hit[0] for hit in record.geofence_hits],
                    "geofence_tenants": [hit[1] for hit in record.geofence_hits],
                    "geofence_versions": [hit[2] for hit in record.geofence_hits],
                    "geofence_relations": [hit[3] for hit in record.geofence_hits],
                },
            )
        ).one()
        if (row.zone_hits, row.geofence_hits) != (len(record.zone_hits), len(record.geofence_hits)):
            raise RuntimeError("stored hit counts differ from the computed geo-context")

    async def get_geo_context_document(self, event_id: str, observed_at: datetime) -> dict[str, Any] | None:
        value = (
            await self._session.execute(_GET_CONTEXT, {"event_id": event_id, "observed_at": observed_at})
        ).scalar_one_or_none()
        return None if value is None else dict(value)
