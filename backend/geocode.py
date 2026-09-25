"""
Reverse geocoding — turns a GPS fix into a short human-readable place name
(e.g. "Tissamaharama, Southern Province") using OpenStreetMap's free
Nominatim API (no key required). Best-effort: never raises, returns None on
any failure/timeout so callers fall back to the seeded zone name.
"""

import json
import urllib.request

TIMEOUT_S = 6


def _fetch(lat: float, lng: float) -> dict | None:
    url = (
        "https://nominatim.openstreetmap.org/reverse"
        f"?format=jsonv2&lat={lat}&lon={lng}&zoom=14&addressdetails=1"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            # Nominatim's usage policy requires an identifying UA/Referer.
            "User-Agent": "DialogSmartAlerts/1.0 (elephant-detection platform)",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reverse_geocode(lat: float, lng: float) -> str | None:
    if lat is None or lng is None:
        return None
    try:
        data = _fetch(lat, lng)
    except Exception:
        return None

    a = (data or {}).get("address") or {}
    place = a.get("village") or a.get("town") or a.get("city") or a.get("suburb") or a.get("county") or a.get("hamlet")
    region = a.get("state") or a.get("state_district")

    if place and region:
        return f"{place}, {region}"
    if place or region:
        return place or region
    display_name = (data or {}).get("display_name")
    if display_name:
        return ", ".join(display_name.split(",")[:2]).strip()
    return None
