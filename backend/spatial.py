"""
Spatial actuation engine.

Computes the state of each actuator (LED board / road sign) from recent
detection events using a radius + time-decay model:

    RED   (WARNING)  — a qualifying detection within `propagation_radius_m`
                       happened less than `red_hold_s` ago    → "definitely around"
    AMBER (CAUTION)  — within radius, less than `amber_hold_s` ago
                       (but older than red_hold)               → "might still be around"
    GREEN (CLEAR)    — nothing recent within radius            → "free to go"
    OFFLINE          — board is offline

Because state is derived purely from (distance, age), a moving animal lights
a travelling "red blob" with an amber trail behind it — no per-target tracking
is required, and the behaviour generalises to any device/actuator layout.
"""

import math
from datetime import datetime, timezone


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance in metres between two lat/lng points."""
    if None in (lat1, lng1, lat2, lng2):
        return float("inf")
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_dt(s) -> datetime:
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(s))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


# Default spatial config used when a use case doesn't define one.
DEFAULT_SPATIAL = {
    "mode":                 "radius",
    "propagation_radius_m": 120,
    "red_hold_s":           90,
    "amber_hold_s":         420,
    "min_confidence":       0,
}


def _radius_state(sign, spatial, events, now) -> str:
    radius     = float(spatial.get("propagation_radius_m", 120))
    red_hold   = float(spatial.get("red_hold_s", 90))
    amber_hold = float(spatial.get("amber_hold_s", 420))
    min_conf   = float(spatial.get("min_confidence", 0))

    s_lat, s_lng = sign.get("lat"), sign.get("lng")
    youngest_age = None

    for e in events:
        if float(e.get("confidence", 0)) < min_conf:
            continue
        dist = haversine_m(s_lat, s_lng, e.get("lat"), e.get("lng"))
        if dist > radius:
            continue
        age = (now - _parse_dt(e.get("received_at"))).total_seconds()
        if age < 0:
            age = 0
        if age <= amber_hold and (youngest_age is None or age < youngest_age):
            youngest_age = age

    if youngest_age is None:
        return "CLEAR"
    if youngest_age <= red_hold:
        return "WARNING"
    return "CAUTION"


def _zone_state(sign, incidents) -> str:
    """Legacy fallback: derive from active incidents in the same zone."""
    nearby = [
        i for i in incidents
        if i.get("zone_id") == sign.get("zone_id")
        and i.get("status") in ("ACTIVE", "OPERATOR_REVIEW")
    ]
    if any(i.get("severity") == "CRITICAL" for i in nearby):
        return "WARNING"
    if any(i.get("severity") in ("HIGH", "MEDIUM") for i in nearby):
        return "CAUTION"
    return "CLEAR"


def compute_states(signs, use_cases, zones, events, incidents, now=None) -> dict:
    """
    Returns { sign_id: state } for every sign.
    Picks radius mode or zone mode per the sign's owning use case.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    uc_by_id   = {u["id"]: u for u in use_cases}
    zone_by_id = {z["id"]: z for z in zones}

    # Only consider reasonably recent events (bounded for performance)
    recent_events = [e for e in events if e.get("lat") is not None]

    out = {}
    for sign in signs:
        if not sign.get("online", True):
            out[sign["id"]] = "OFFLINE"
            continue

        zone = zone_by_id.get(sign.get("zone_id"), {})
        uc   = uc_by_id.get(zone.get("use_case_id"))
        spatial = (uc or {}).get("spatial") or DEFAULT_SPATIAL

        if spatial.get("mode") == "radius":
            out[sign["id"]] = _radius_state(sign, spatial, recent_events, now)
        else:
            out[sign["id"]] = _zone_state(sign, incidents)

    return out
