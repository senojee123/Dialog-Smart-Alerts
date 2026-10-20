"""The development seed: the sample tenant, its objects and enriched events, through the real services."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.db.session import transaction
from app.tools.seed_dev_data import read_sample, seed
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import OPEN_RELEASE

SAMPLE = Path(__file__).resolve().parents[3] / "data" / "sample" / "operational" / "wildlife-dept.json"


async def test_the_sample_is_seeded_once_and_its_events_keep_their_release(
    spatial_world: SpatialWorld,
) -> None:
    sample = read_sample(SAMPLE)
    first = await seed(sample, spatial_world.settings)
    assert first.tenant_created
    assert set(first.sites.values()) == set(first.devices.values()) == {"created"}
    assert set(first.geofences.values()) == {"created"}
    assert len(first.events) == len(sample.events)
    # Every geo-context names the release it was computed with.
    assert {event["refDataRelease"] for event in first.events} == {OPEN_RELEASE}
    by_key = {event["eventId"].rsplit("-", 1)[1]: event for event in first.events}
    assert by_key["05"]["geofenceHits"] == ["DEV Palugaswewa village perimeter"]
    assert by_key["08"]["geofenceHits"] == ["DEV Habarana junction watch zone"]
    assert "DEV A11 Minneriya crossing corridor" in by_key["04"]["geofenceHits"]

    again = await seed(sample, spatial_world.settings, events=False)
    assert not again.tenant_created
    assert set(again.sites.values()) == set(again.devices.values()) == {"exists"}
    assert set(again.geofences.values()) == {"exists"}
    assert again.events == []

    async with transaction(spatial_world.migrator_sessions) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT l.event_id, l.field_of_view_id IS NOT NULL AS in_view, c.release_code
                    FROM geo.event_location l
                    JOIN geo.event_geo_context c USING (tenant_id, event_id, observed_at)
                    WHERE l.tenant_id = 'wildlife-dept'
                    """
                )
            )
        ).all()
        sites = await session.scalar(text("SELECT count(*) FROM ops.site WHERE tenant_id = 'wildlife-dept'"))
    assert len(rows) == len(sample.events)
    assert {row.release_code for row in rows} == {OPEN_RELEASE}
    # A field of view is in effect from when it was recorded: only the event of the seeding instant
    # (hb-cam-01, 0 minutes before) falls inside one.
    assert [row.event_id.rsplit("-", 1)[1] for row in rows if row.in_view] == ["10"]
    assert sites == len(sample.sites)
