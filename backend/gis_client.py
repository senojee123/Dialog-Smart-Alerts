"""
GIS instance connector.

The GIS service (services/gis) is the platform's geospatial instance: PostGIS reference data, geo-context
enrichment, spatial queries and the GIS map. It runs as its own internal service; this module is the only
place the platform talks to it:

  • proxy      /api/gis/*  → GIS API      (the GIS map's calls)
               /gis-app/*  → GIS /app/*   (the built GIS map, shown in a frame on the /gis page)
               /basemap/*  → GIS /basemap/* (offline basemap: style, fonts, PMTiles with range requests)
  • enrich     every detection with a location is sent to POST /geo/v1/enrich; the answer (district,
               nearest town and road, national parks, geofence hits, nearby devices) is stored on the event
  • devices    registered devices are placed on the GIS map (PUT /geo/v1/devices/{id}/placement)

The GIS checks no credentials (the platform owns sign-in), so it must only be reachable from here, on the
internal network. A GIS that is down or slow never blocks a detection: enrichment times out
(GIS_ENRICH_TIMEOUT_S) and the event carries on without a geo-context.

Settings (environment):
  GIS_ENABLED           "false" turns everything here off (default: true)
  GIS_API_URL           where the GIS service is (default: http://localhost:8100)
  GIS_TENANT_ID         the organisation the platform acts for in the GIS (default: dialog-smart-alerts)
  GIS_ENRICH_TIMEOUT_S  how long a detection waits for its geo-context (default: 2)
"""

import asyncio
import os
import re
import time
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask

import data_store

GIS_ENABLED       = os.getenv("GIS_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")
GIS_API_URL       = os.getenv("GIS_API_URL", "http://localhost:8100").rstrip("/")
GIS_TENANT_ID     = os.getenv("GIS_TENANT_ID", "dialog-smart-alerts").strip()
ENRICH_TIMEOUT_S  = float(os.getenv("GIS_ENRICH_TIMEOUT_S", "2"))

# Device ids in the GIS are UUIDs: each platform device gets a fixed one derived from its own id, so
# both sides always agree without storing a mapping.
_DEVICE_NAMESPACE = uuid.UUID("6f1c2d3e-8a4b-5c6d-9e0f-1a2b3c4d5e6f")

# Platform device types → GIS device types. Roaming producers (a citizen's phone, a drone) have no fixed
# place, so they are not placed on the GIS map.
_DEVICE_TYPES = {
    "camera": "camera", "thermal": "camera", "acoustic": "acoustic_sensor",
    "pressure_pad": "seismic_sensor", "siren": "other", "gate": "other",
}
_NOT_PLACED = {"manual", "drone"}

# Platform event source → GIS sourceType.
_SOURCE_TYPES = {"device": "sensor", "ingestion": "external", "upload": "manual", "simulation": "external"}

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        headers = {"X-GIS-Tenant-Id": GIS_TENANT_ID} if GIS_TENANT_ID else {}
        _client = httpx.AsyncClient(base_url=GIS_API_URL, headers=headers, timeout=httpx.Timeout(30.0, connect=3.0))
    return _client


async def close():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def gis_device_id(platform_device_id: str) -> str:
    return str(uuid.uuid5(_DEVICE_NAMESPACE, f"dialog-smart-alerts:device:{platform_device_id}"))


# ════════════════════════════════════════════════════════════════════════════
# PROXY  —  the browser reaches the GIS only through the platform
# ════════════════════════════════════════════════════════════════════════════

router = APIRouter()

# Request headers worth passing on; everything else (cookies, hop-by-hop headers) stays here.
_FORWARD_REQUEST = ("accept", "content-type", "range", "if-none-match", "if-modified-since", "x-request-id")
_HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
               "proxy-authenticate", "proxy-authorization"}


async def _forward(request: Request, target: str):
    if not GIS_ENABLED:
        return JSONResponse({"detail": "The GIS instance is turned off (GIS_ENABLED=false)"}, status_code=503)
    headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD_REQUEST}
    body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
    outgoing = _http().build_request(
        request.method, target, params=request.query_params.multi_items(), headers=headers, content=body
    )
    try:
        upstream = await _http().send(outgoing, stream=True)
    except httpx.HTTPError as e:
        print(f"[GIS] proxy {request.method} {target} failed: {type(e).__name__}")
        return JSONResponse({"detail": "The GIS service is not reachable"}, status_code=502)
    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
        background=BackgroundTask(upstream.aclose),
    )


@router.api_route("/api/gis/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_gis_api(path: str, request: Request):
    return await _forward(request, f"/{path}")


@router.get("/gis-app")
async def gis_app_root():
    return RedirectResponse("/gis-app/")


@router.get("/gis-app/{path:path}")
async def proxy_gis_app(path: str, request: Request):
    return await _forward(request, f"/app/{path}")


@router.get("/basemap/{path:path}")
async def proxy_basemap(path: str, request: Request):
    return await _forward(request, f"/basemap/{path}")


# ════════════════════════════════════════════════════════════════════════════
# ENRICHMENT  —  where a detection is, and what is around it
# ════════════════════════════════════════════════════════════════════════════

def _event_type(event: dict) -> str:
    """`detection.<object>` in the dotted lower case the GIS expects, e.g. detection.elephant."""
    obj = re.sub(r"[^a-z0-9_]+", "_", str(event.get("object_type") or "unknown").lower()).strip("_")
    if not obj or not obj[0].isalpha():
        obj = f"object_{obj}" if obj else "unknown"
    return f"detection.{obj[:80]}"


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _observed_at(event: dict) -> str | None:
    """When the detection happened, with an offset: the producer's captured_at if it says so, else receipt."""
    from datetime import datetime
    captured = event.get("captured_at")
    if captured:
        try:
            if datetime.fromisoformat(str(captured).replace("Z", "+00:00")).tzinfo is not None:
                return str(captured)
        except ValueError:
            pass
    return event.get("received_at")


def enrich_request(event: dict, device: dict | None, with_device: bool = True) -> dict | None:
    """The POST /geo/v1/enrich body for a stored detection, or None when it has no position."""
    lat, lng = _float(event.get("lat")), _float(event.get("lng"))
    if lat is None or lng is None:
        return None
    body = {
        "eventId":         event["id"],
        "tenantId":        GIS_TENANT_ID,
        "observedAt":      _observed_at(event),
        "eventType":       _event_type(event),
        "sourceType":      _SOURCE_TYPES.get(event.get("source"), "external"),
        # The platform's device id - never the device's external_id, which falls back to its api_key.
        "sourceRef":       str(event.get("device_id") or "")[:200] or None,
        "location":        {"type": "Point", "coordinates": [lng, lat]},   # GeoJSON: [longitude, latitude]
        "locationSource":  "sensor",
        "metadata": {
            "platformSource": event.get("source"),
            "objectType":     event.get("object_type"),
            "confidence":     event.get("confidence"),
            "useCaseId":      event.get("use_case_id"),
            "zoneId":         event.get("zone_id"),
        },
    }
    if with_device and device and device.get("type") not in _NOT_PLACED:
        body["deviceId"] = gis_device_id(device["id"])
    return body


async def enrich_event(event: dict, device: dict | None) -> dict | None:
    """The event's geo-context from the GIS, or None (no position, GIS off, slow, down or refusing)."""
    if not GIS_ENABLED:
        return None
    body = enrich_request(event, device)
    if body is None:
        return None
    try:
        response = await _http().post("/geo/v1/enrich", json=body, timeout=ENRICH_TIMEOUT_S)
        if response.status_code == 404 and "deviceId" in body:
            # The device is not placed in the GIS (yet): place it, and enrich by position meanwhile.
            if device:
                asyncio.create_task(sync_device(device))
            response = await _http().post("/geo/v1/enrich", json=enrich_request(event, device, with_device=False),
                                          timeout=ENRICH_TIMEOUT_S)
        if response.status_code != 200:
            print(f"[GIS] enrich {event['id']} → HTTP {response.status_code}: {response.text[:200]}")
            return None
        return response.json()
    except httpx.HTTPError as e:
        print(f"[GIS] enrich {event['id']} skipped: {type(e).__name__}")
        return None


def _name(item: dict | None) -> str | None:
    return (item or {}).get("name") if isinstance(item, dict) else None


def summarise(context: dict | None) -> dict | None:
    """The parts of a geo-context an operator reads first, in the platform's snake_case."""
    if not context:
        return None
    admin = context.get("admin") or {}
    settlement = context.get("nearestSettlement") or {}
    road = context.get("nearestRoad") or {}
    return {
        "province":           _name(admin.get("province")),
        "district":           _name(admin.get("district")),
        "ds_division":        _name(admin.get("dsDivision")),
        "gn_division":        _name(admin.get("gnDivision")),
        "nearest_settlement": settlement.get("name"),
        "settlement_distance_m": settlement.get("distanceM"),
        "nearest_road":       road.get("name") or road.get("refCode") or road.get("class"),
        "road_class":         road.get("class"),
        "road_distance_m":    road.get("distanceM"),
        "inside_zones":       [z.get("name") for z in context.get("insideZones") or [] if z.get("name")],
        "geofence_hits":      [g.get("name") for g in context.get("geofenceHits") or [] if g.get("name")],
        "nearby_devices":     len(context.get("nearestDevices") or []),
        "ref_data_release":   context.get("refDataRelease"),
        "event_id":           context.get("eventId"),
    }


def incident_gis(events: list[dict]) -> dict | None:
    """The GIS summary of an incident: that of its latest detection with a geo-context."""
    with_context = [e for e in events if e.get("geo_context")]
    if not with_context:
        return None
    latest = max(with_context, key=lambda e: e.get("received_at", ""))
    return summarise(latest["geo_context"])


# ════════════════════════════════════════════════════════════════════════════
# DEVICES  —  the registry's devices on the GIS map
# ════════════════════════════════════════════════════════════════════════════

def placement_body(device: dict) -> dict | None:
    """The GIS placement of a platform device, or None when it cannot be placed."""
    lat, lng = _float(device.get("lat")), _float(device.get("lng"))
    if lat is None or lng is None or device.get("type") in _NOT_PLACED:
        return None
    disabled = str(device.get("status", "")).lower() == "disabled"
    return {
        "name":           str(device.get("name") or device["id"])[:200],
        "deviceType":     _DEVICE_TYPES.get(device.get("type"), "other"),
        "externalId":     device["id"],
        "status":         "inactive" if disabled else "active",
        "position":       {"type": "Point", "coordinates": [lng, lat]},
        "positionSource": "digitised",
        "attributes": {
            "platformType": device.get("type"),
            "zoneId":       device.get("zone_id"),
            "useCaseId":    device.get("use_case_id"),
        },
    }


async def _put_placement(device_id: str, body: dict) -> bool:
    path = f"/geo/v1/devices/{gis_device_id(device_id)}/placement"
    current = await _http().get(path)
    if current.status_code == 200:
        body = {**body, "version": current.json()["version"]}
    elif current.status_code != 404:
        print(f"[GIS] device {device_id}: reading its placement → HTTP {current.status_code}")
        return False
    response = await _http().put(path, json=body)
    if response.status_code not in (200, 201):
        print(f"[GIS] device {device_id}: placement → HTTP {response.status_code}: {response.text[:200]}")
        return False
    return True


async def sync_device(device: dict) -> bool:
    """Place (or move) one device on the GIS map. Never raises."""
    if not GIS_ENABLED:
        return False
    body = placement_body(device)
    if body is None:
        return False
    try:
        return await _put_placement(device["id"], body)
    except httpx.HTTPError as e:
        print(f"[GIS] device {device.get('id')} not synced: {type(e).__name__}")
        return False


async def retire_device(device: dict) -> bool:
    """Mark a deleted device decommissioned in the GIS (its history stays). Never raises."""
    if not GIS_ENABLED:
        return False
    body = placement_body(device)
    if body is None:
        return False
    body.update({"status": "decommissioned", "decommissionedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    try:
        return await _put_placement(device["id"], body)
    except httpx.HTTPError as e:
        print(f"[GIS] device {device.get('id')} not retired: {type(e).__name__}")
        return False


async def sync_all_devices(attempts: int = 10, delay_s: float = 15.0):
    """At start-up: place every registered device, waiting for the GIS if it is still starting."""
    if not GIS_ENABLED:
        return
    for attempt in range(1, attempts + 1):
        if await ready():
            devices = data_store.get_all("devices")
            placed = [d for d in devices if await sync_device(d)]
            print(f"[GIS] {len(placed)}/{len(devices)} devices placed on the GIS map")
            return
        await asyncio.sleep(delay_s)
    print("[GIS] not reachable at start-up; devices are placed when they are next saved")


# ════════════════════════════════════════════════════════════════════════════
# HEALTH
# ════════════════════════════════════════════════════════════════════════════

_ready_cache: tuple[float, bool] = (0.0, False)


async def ready() -> bool:
    """Whether the GIS answers ready (cached for 15 s, so the dashboard's polling stays cheap)."""
    global _ready_cache
    if not GIS_ENABLED:
        return False
    checked, value = _ready_cache
    if time.monotonic() - checked < 15:
        return value
    try:
        value = (await _http().get("/health/ready", timeout=2.0)).status_code == 200
    except httpx.HTTPError:
        value = False
    _ready_cache = (time.monotonic(), value)
    return value
