"""Seed a development database with a tenant's sample operational data and enriched events.

Usage (from ``backend/``, with the ``GIS_DB_*`` settings of both logins)::

    python -m app.tools.seed_dev_data ../data/sample/operational/wildlife-dept.json

What it does, in order:

1. registers the tenant in ``meta.tenant`` (migration login; the API login cannot);
2. creates the tenant's sites, devices (with their fields of view) and geofences through the same
   service the API uses, so every rule, trigger and audit entry applies;
3. enriches a batch of sample events through the geo-context engine against the current reference data
   release, so each stored geo-context names the release it was computed with (``refDataRelease``).

Steps 1 and 2 are idempotent: objects are matched by their external id (sites, geofences) or their
identifier (devices, derived from the tenant and the sample key) and left alone when they exist. Each run
adds one batch of events, observed in the 24 hours before the run, so the map's default event window has
something to show; ``--no-events`` leaves them out.

The sample is development data and says so (names start with ``DEV``, attributes carry ``sample: true``).
The tool refuses to run with ``GIS_ENV=production``, and when the current reference data release is not a
development or test release.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access import Access
from app.core.config import DbRole, Environment, Settings, get_settings
from app.core.errors import GisError
from app.core.logging import configure_logging
from app.core.tenancy import TenantId
from app.db.engine import create_engine, create_session_factory
from app.db.session import transaction
from app.schemas.base import ApiModel
from app.schemas.events import EVENT_TYPE_PATTERN, EventLocationIn, SourceType
from app.schemas.geo_context import LocationSource
from app.schemas.geojson import GeoJsonGeometry
from app.schemas.operational import (
    DevicePlacementIn,
    GeofenceIn,
    OperationalListQuery,
    SiteIn,
)
from app.services.enrichment.service import GeoContextService
from app.services.operational import OperationalService
from app.spatial.service_area import ServiceArea

ACTOR: Final = "dev-seed"
KEY_PATTERN: Final = r"^[a-z0-9][a-z0-9-]{0,62}$"
EXTERNAL_ID_PREFIX: Final = "dev-sample:"
# Device identifiers are derived from the tenant and the sample key, so a second run finds them again.
DEVICE_NAMESPACE: Final = uuid.UUID("5d0c3c7e-2f0b-4d57-9a53-6f1b8a0e4c11")
SAMPLE_RELEASE_PURPOSES: Final = frozenset({"development", "test"})


class SeedRefusedError(GisError):
    status_code = 409
    code = "seed_refused"
    title = "Development sample data cannot be seeded here"


class SampleTenant(ApiModel):
    tenant_id: str
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["organisation", "authority"] = "organisation"


class SampleSite(SiteIn):
    key: str = Field(pattern=KEY_PATTERN)


class SampleDevice(DevicePlacementIn):
    key: str = Field(pattern=KEY_PATTERN)
    site: str | None = Field(default=None, pattern=KEY_PATTERN, description="Key of the site.")


class SampleGeofence(GeofenceIn):
    key: str = Field(pattern=KEY_PATTERN)


class SampleEvent(ApiModel):
    key: str = Field(pattern=KEY_PATTERN)
    minutes_before: int = Field(ge=0, le=24 * 60, description="Observed this long before the batch time.")
    device: str | None = Field(default=None, pattern=KEY_PATTERN, description="Key of the device.")
    event_type: str = Field(pattern=EVENT_TYPE_PATTERN, max_length=100)
    event_subtype: str | None = Field(default=None, max_length=100)
    source_type: SourceType
    source_ref: str | None = Field(default=None, max_length=200)
    location_source: LocationSource
    location: GeoJsonGeometry | None = None
    location_accuracy_m: float | None = Field(default=None, gt=0, le=100_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Sample(ApiModel):
    description: str
    tenant: SampleTenant
    sites: list[SampleSite] = Field(default_factory=list)
    devices: list[SampleDevice] = Field(default_factory=list)
    geofences: list[SampleGeofence] = Field(default_factory=list)
    events: list[SampleEvent] = Field(default_factory=list)


@dataclass(slots=True)
class SeedResult:
    tenant: str
    release: str
    tenant_created: bool = False
    sites: dict[str, str] = field(default_factory=dict)
    devices: dict[str, str] = field(default_factory=dict)
    geofences: dict[str, str] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant": self.tenant,
            "tenantCreated": self.tenant_created,
            "refDataRelease": self.release,
            "sites": self.sites,
            "devices": self.devices,
            "geofences": self.geofences,
            "events": self.events,
        }


def read_sample(path: Path) -> Sample:
    try:
        sample = Sample.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise SeedRefusedError(f"{path} is not a valid sample: {exc}") from exc
    keys = {item.key for item in sample.sites}
    devices = {item.key for item in sample.devices}
    unknown = sorted(
        ({item.site for item in sample.devices if item.site is not None} - keys)
        | ({item.device for item in sample.events if item.device is not None} - devices)
    )
    if unknown:
        raise SeedRefusedError(f"{path} refers to sites or devices it does not define: {', '.join(unknown)}")
    for label, items in (
        ("site", sample.sites),
        ("device", sample.devices),
        ("geofence", sample.geofences),
        ("event", sample.events),
    ):
        seen = [item.key for item in items]
        if len(seen) != len(set(seen)):
            raise SeedRefusedError(f"{path} repeats a {label} key")
    return sample


def device_id(tenant: str, key: str) -> uuid.UUID:
    return uuid.uuid5(DEVICE_NAMESPACE, f"{tenant}/{key}")


def external_id(key: str) -> str:
    return f"{EXTERNAL_ID_PREFIX}{key}"


def refuse_production(settings: Settings) -> None:
    if settings.env == Environment.PRODUCTION:
        raise SeedRefusedError("sample data is for development: GIS_ENV is production")


async def _register_tenant(migrator: async_sessionmaker[AsyncSession], tenant: SampleTenant) -> bool:
    async with transaction(migrator) as session:
        created = await session.execute(
            text(
                "INSERT INTO meta.tenant (tenant_id, name, kind) VALUES (:tenant_id, :name, :kind) "
                "ON CONFLICT (tenant_id) DO NOTHING RETURNING tenant_id"
            ),
            {"tenant_id": tenant.tenant_id, "name": tenant.name, "kind": tenant.kind},
        )
        return created.scalar_one_or_none() is not None


async def _current_release(app: async_sessionmaker[AsyncSession]) -> tuple[str, str]:
    async with transaction(app) as session:
        row = (
            await session.execute(text("SELECT code, purpose FROM meta.ref_data_release WHERE is_current"))
        ).one_or_none()
    if row is None:
        raise SeedRefusedError(
            "there is no current reference data release; load one first "
            "(python -m app.pipeline load ../data/sample/ref-2026.09-dev --current)"
        )
    if row.purpose not in SAMPLE_RELEASE_PURPOSES:
        raise SeedRefusedError(
            f"the current reference data release {row.code} is a {row.purpose} release; sample data is "
            "only seeded next to development or test releases",
            extensions={"refDataRelease": row.code},
        )
    return str(row.code), str(row.purpose)


def _payload(model: ApiModel, *, exclude: set[str], **update: Any) -> dict[str, Any]:
    values = model.model_dump(by_alias=True, exclude=exclude, exclude_none=True)
    values.update(update)
    return values


async def _seed_sites(
    service: OperationalService, access: Access, sample: Sample, result: SeedResult
) -> dict[str, uuid.UUID]:
    by_external: dict[str, uuid.UUID] = {}
    cursor: str | None = None
    while True:
        page = await service.sites(access, OperationalListQuery(owned_only=True, limit=1000, cursor=cursor))
        by_external.update({item.external_id: item.id for item in page.items if item.external_id})
        cursor = page.next_cursor
        if cursor is None:
            break
    ids: dict[str, uuid.UUID] = {}
    for site in sample.sites:
        known = by_external.get(external_id(site.key))
        if known is None:
            created = await service.create_site(
                access,
                SiteIn.model_validate(_payload(site, exclude={"key"}, externalId=external_id(site.key))),
            )
            known = created.id
            result.sites[site.key] = "created"
        else:
            result.sites[site.key] = "exists"
        ids[site.key] = known
    return ids


async def _seed_devices(
    service: OperationalService,
    access: Access,
    sample: Sample,
    sites: dict[str, uuid.UUID],
    result: SeedResult,
) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for device in sample.devices:
        identifier = device_id(sample.tenant.tenant_id, device.key)
        ids[device.key] = identifier
        try:
            await service.placement(access, identifier)
        except GisError as exc:
            if exc.status_code != 404:
                raise
        else:
            result.devices[device.key] = "exists"
            continue
        body = DevicePlacementIn.model_validate(
            _payload(
                device,
                exclude={"key", "site"},
                externalId=external_id(device.key),
                siteId=None if device.site is None else str(sites[device.site]),
            )
        )
        await service.put_placement(access, identifier, body)
        result.devices[device.key] = "created"
    return ids


async def _seed_geofences(
    service: OperationalService, access: Access, sample: Sample, result: SeedResult
) -> None:
    # Every page: archived geofences are listed too, and a tenant used for testing collects many.
    known: set[str] = set()
    cursor: str | None = None
    while True:
        page = await service.geofences(
            access, OperationalListQuery(owned_only=True, limit=1000, cursor=cursor)
        )
        known.update(item.external_id for item in page.items if item.external_id)
        cursor = page.next_cursor
        if cursor is None:
            break
    for geofence in sample.geofences:
        if external_id(geofence.key) in known:
            result.geofences[geofence.key] = "exists"
            continue
        await service.create_geofence(
            access,
            GeofenceIn.model_validate(
                _payload(geofence, exclude={"key"}, externalId=external_id(geofence.key))
            ),
        )
        result.geofences[geofence.key] = "created"


async def _seed_events(
    engine: GeoContextService,
    access: Access,
    sample: Sample,
    devices: dict[str, uuid.UUID],
    batch: datetime,
    result: SeedResult,
) -> None:
    prefix = f"dev-{batch:%Y%m%dT%H%M%SZ}"
    for event in sorted(sample.events, key=lambda item: -item.minutes_before):
        body = EventLocationIn.model_validate(
            _payload(
                event,
                exclude={"key", "minutes_before", "device"},
                eventId=f"{prefix}-{event.key}",
                tenantId=sample.tenant.tenant_id,
                observedAt=(batch - timedelta(minutes=event.minutes_before)).isoformat(),
                deviceId=None if event.device is None else str(devices[event.device]),
            )
        )
        context = await engine.enrich(body, access=access)
        result.events.append(
            {
                "eventId": context.event_id,
                "observedAt": context.observed_at.isoformat(),
                "refDataRelease": context.ref_data_release,
                "insideZones": [item.name for item in context.inside_zones],
                "geofenceHits": [item.name for item in context.geofence_hits],
            }
        )


async def seed(
    sample: Sample, settings: Settings, *, events: bool = True, now: datetime | None = None
) -> SeedResult:
    refuse_production(settings)
    tenant = TenantId(sample.tenant.tenant_id)
    migrator_engine = create_engine(settings, DbRole.MIGRATOR)
    app_engine = create_engine(settings, DbRole.APP)
    try:
        app = create_session_factory(app_engine)
        release, _ = await _current_release(app)
        result = SeedResult(tenant=tenant.value, release=release)
        result.tenant_created = await _register_tenant(create_session_factory(migrator_engine), sample.tenant)
        area = ServiceArea.from_bbox(settings.service_area_bbox)
        access = Access.system(ACTOR, tenant, channel="loader")
        operational = OperationalService(app, area)
        sites = await _seed_sites(operational, access, sample, result)
        devices = await _seed_devices(operational, access, sample, sites, result)
        await _seed_geofences(operational, access, sample, result)
        if events:
            # After the devices: a field of view is in effect from the moment it is recorded, so only the
            # events of this instant fall inside one.
            batch = now or datetime.now(UTC)
            await _seed_events(GeoContextService(app, area), access, sample, devices, batch, result)
        return result
    finally:
        await app_engine.dispose()
        await migrator_engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("sample", type=Path, help="sample definition (data/sample/operational/*.json)")
    parser.add_argument("--no-events", action="store_true", help="seed the objects only, no events")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        sample = read_sample(args.sample)
        result = asyncio.run(seed(sample, settings, events=not args.no_events))
    except GisError as exc:
        print(
            json.dumps({"error": exc.code, "detail": exc.detail, **exc.extensions}, indent=2), file=sys.stderr
        )
        return 1
    print(json.dumps(result.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
