"""Read-only database platform facts used by readiness checks."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Integer, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class ServerInfo:
    server_version: str
    database: str


@dataclass(frozen=True, slots=True)
class PostgisInfo:
    extension_version: str
    lib_version: str
    geos_version: str
    proj_version: str


_SERVER_INFO = text(
    "SELECT current_setting('server_version') AS server_version, current_database() AS database"
)
_EXTENSION_VERSION = text("SELECT extversion FROM pg_catalog.pg_extension WHERE extname = :name")
_POSTGIS_LIBS = text(
    "SELECT public.postgis_lib_version() AS lib, public.postgis_geos_version() AS geos, "
    "public.postgis_proj_version() AS proj"
)
_SRIDS_PRESENT = text(
    "SELECT srid FROM public.spatial_ref_sys WHERE srid = ANY(:srids) ORDER BY srid"
).bindparams(bindparam("srids", type_=ARRAY(Integer)))
_TRANSFORM_POINT = text(
    "SELECT public.ST_X(g) AS x, public.ST_Y(g) AS y FROM ("
    "  SELECT public.ST_Transform("
    "    public.ST_SetSRID(public.ST_MakePoint(CAST(:x AS double precision), CAST(:y AS double precision)),"
    "      CAST(:source_srid AS integer)),"
    "    CAST(:target_srid AS integer)) AS g"
    ") AS t"
)
# Whether the geometry bounding-box operator (&&) is LEAKPROOF (db/admin/postgis-leakproof.sql).
_OVERLAP_OPERATOR_LEAKPROOF = text(
    """
    SELECT p.proleakproof
    FROM pg_catalog.pg_operator AS o
    JOIN pg_catalog.pg_proc AS p ON p.oid = o.oprcode
    WHERE o.oprname = '&&'
      AND o.oprleft = to_regtype('public.geometry')
      AND o.oprright = to_regtype('public.geometry')
    """
)
_VERSION_TABLE_EXISTS = text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
_MIGRATION_REVISIONS = text("SELECT version_num FROM public.alembic_version")


class DatabaseInfoRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def server_info(self) -> ServerInfo:
        row = (await self._connection.execute(_SERVER_INFO)).one()
        return ServerInfo(server_version=row.server_version, database=row.database)

    async def extension_version(self, name: str) -> str | None:
        value = (await self._connection.execute(_EXTENSION_VERSION, {"name": name})).scalar_one_or_none()
        return None if value is None else str(value)

    async def postgis_info(self) -> PostgisInfo | None:
        extension_version = await self.extension_version("postgis")
        if extension_version is None:
            return None
        row = (await self._connection.execute(_POSTGIS_LIBS)).one()
        return PostgisInfo(
            extension_version=extension_version,
            lib_version=str(row.lib),
            geos_version=str(row.geos),
            # postgis_proj_version() appends build paths after the version number; keep only the version.
            proj_version=str(row.proj).split(" ", 1)[0],
        )

    async def present_srids(self, srids: frozenset[int]) -> frozenset[int]:
        result = await self._connection.execute(_SRIDS_PRESENT, {"srids": sorted(srids)})
        return frozenset(int(value) for value in result.scalars())

    async def transform_point(
        self, x: float, y: float, source_srid: int, target_srid: int
    ) -> tuple[float, float]:
        row = (
            await self._connection.execute(
                _TRANSFORM_POINT,
                {"x": x, "y": y, "source_srid": source_srid, "target_srid": target_srid},
            )
        ).one()
        return float(row.x), float(row.y)

    async def overlap_operator_is_leakproof(self) -> bool | None:
        """None when the operator does not exist (PostGIS missing)."""
        value = (await self._connection.execute(_OVERLAP_OPERATOR_LEAKPROOF)).scalar_one_or_none()
        return None if value is None else bool(value)

    async def migration_revisions(self) -> frozenset[str] | None:
        """Applied Alembic revisions, or ``None`` when the schema is not migrated (never, or down to base)."""
        if not (await self._connection.execute(_VERSION_TABLE_EXISTS)).scalar_one():
            return None
        result = await self._connection.execute(_MIGRATION_REVISIONS)
        revisions = frozenset(str(value) for value in result.scalars())
        return revisions or None
