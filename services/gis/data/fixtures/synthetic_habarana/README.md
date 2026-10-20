# Synthetic fixture world (near Habarana)

Constructed geometry for tests that need exact answers. It is **not a real place**: every name starts
with "Fixture", every row has `geometry_source = synthetic`, and it is loaded into its own release
(`ref-2026.09-fixture`), never mixed with real reference data. Licence: CC0-1.0.

Regenerate with `python ../data/fixtures/synthetic_habarana/build.py` (from `backend/`). The layout is
described in `build.py`.

| File | What it tests |
|---|---|
| `admin_level1..4.geojson` | A province split into two districts along lon 80.75 and DS divisions along lat 8.03. The point (80.75, 8.03) lies on the district edge and the corner of three DS divisions (boundary handling, `onBoundary`). Parents are linked by code. |
| `protected_areas.geojson` | A national park with an enclave (a point in the hole is outside); an invalid bow-tie reserve that the database repairs into two triangles and logs in `meta.geometry_repair`; a sanctuary that overlaps two risk zones. |
| `risk_zones.geojson` | An elephant corridor (always valid), a flood zone valid only in the 2025 north-east monsoon (time-dependent zone hits) and a drought zone. The point (80.758, 8.015) lies in the corridor, the drought zone and the sanctuary (multiple zone hits). |
| `settlements.geojson` | A town footprint (distance 0 inside) and a village point (distance to a point). |
| `facilities.geojson` | Two valid facilities, one in Chennai (rejected: outside the service area) and one with swapped coordinates (rejected: `likelySwapped`). |
| `roads.geojson` | A straight road along lat 8.01 (distances and corridor geofences) and a track. |
| `water_bodies.geojson` | A tank (polygon) and a stream (line). |

Operational fixtures that use this world (tenants, sites, devices, a field of view and geofences) are
created by `backend/tests/integration/spatial_world.py`.
