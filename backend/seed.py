"""
Seed the data store with the Elephant Detection use case.
Runs once on server startup when data/ is empty.

Geography note: the B43 corridor is laid out as a real line of points running
roughly north along longitude 81.4800. Signs are ~55 m apart (0.0005°) and
cameras are interleaved every ~165 m. With a 120 m propagation radius, one
detection lights ~2 signs on each side — and a detection moving camera→camera
makes the lit region travel up the road.
"""

import asyncio
import repo

LNG = 81.4800  # B43 corridor runs along this longitude


async def run():
    if await repo.count("use_cases") > 0:
        return  # Already seeded

    print("[SEED] Initialising Elephant Detection use case...")

    # ── Use Case (with spatial actuation config) ────────────────────────────
    await repo.upsert("use_cases", {
        "id":          "UC-001",
        "name":        "Elephant Detection – Road Corridor",
        "description": "Detect elephants near road corridors and alert stakeholders. "
                       "Nearby LED boards light automatically by proximity to the detection.",
        "active":      True,
        "icon":        "elephant",
        "color":       "#D92D20",
        "spatial": {
            "mode":                 "radius",
            "propagation_radius_m": 120,   # signs within this of a detection react
            "red_hold_s":           90,    # RED while last detection < 90s ago
            "amber_hold_s":         420,   # AMBER until 7 min after last detection
            "min_confidence":       55,    # ignore weak detections
        },
    })

    # ── Zones ───────────────────────────────────────────────────────────────
    zones = [
        {"id": "ZONE-B43", "name": "B43 Yala Road Corridor", "use_case_id": "UC-001", "road": "B43", "lat": 6.3818, "lng": LNG},
        {"id": "ZONE-A2",  "name": "A2 Southern Highway",     "use_case_id": "UC-001", "road": "A2",  "lat": 6.2812, "lng": 81.3902},
        {"id": "ZONE-KTR", "name": "Kataragama Road",         "use_case_id": "UC-001", "road": "KTR", "lat": 6.3720, "lng": 81.3310},
    ]
    for z in zones:
        await repo.upsert("zones", z)

    # ── Devices ──────────────────────────────────────────────────────────────
    # Three sensors interleaved along the B43 corridor, plus two on other roads.
    devices = [
        {"id": "DEV-001", "name": "Camera Trap – B43 km 1.0",  "type": "camera",  "zone_id": "ZONE-B43", "use_case_id": "UC-001", "lat": 6.3805, "lng": LNG,     "api_key": "dev-key-001", "online": True},
        {"id": "DEV-002", "name": "Camera Trap – B43 km 1.2",  "type": "camera",  "zone_id": "ZONE-B43", "use_case_id": "UC-001", "lat": 6.3820, "lng": LNG,     "api_key": "dev-key-002", "online": True},
        {"id": "DEV-003", "name": "Thermal Sensor – B43 km 1.4","type": "thermal", "zone_id": "ZONE-B43", "use_case_id": "UC-001", "lat": 6.3835, "lng": LNG,     "api_key": "dev-key-003", "online": True},
        {"id": "DEV-004", "name": "Camera Trap – A2 Junction",  "type": "camera",  "zone_id": "ZONE-A2",  "use_case_id": "UC-001", "lat": 6.2812, "lng": 81.3902, "api_key": "dev-key-004", "online": True},
        {"id": "DEV-005", "name": "Camera Trap – Kataragama Rd","type": "camera",  "zone_id": "ZONE-KTR", "use_case_id": "UC-001", "lat": 6.3720, "lng": 81.3310, "api_key": "dev-key-005", "online": False},
    ]
    for d in devices:
        await repo.upsert("devices", d)

    # ── Stakeholders ────────────────────────────────────────────────────────
    stakeholders = [
        {
            "id": "SH-001", "name": "Park Warden – Yala",
            "role": "Wildlife Officer", "org": "Department of Wildlife Conservation",
            "use_case_ids": ["UC-001"],
            "channels": [
                {"type": "sms",      "address": "+94771000001", "language": "en"},
                {"type": "whatsapp", "address": "+94771000001", "language": "en"},
            ],
            "on_call": True,
        },
        {
            "id": "SH-002", "name": "Traffic Control – Southern Province",
            "role": "Traffic Controller", "org": "Road Development Authority",
            "use_case_ids": ["UC-001"],
            "channels": [
                {"type": "sms",   "address": "+94771000002", "language": "en"},
                {"type": "email", "address": "traffic@rda.lk", "language": "en"},
            ],
            "on_call": True,
        },
        {
            "id": "SH-003", "name": "Police – Tissamaharama",
            "role": "Law Enforcement", "org": "Sri Lanka Police",
            "use_case_ids": ["UC-001"],
            "channels": [
                {"type": "sms", "address": "+94771000003", "language": "en"},
            ],
            "on_call": False,
        },
        {
            "id": "SH-004", "name": "DWC Operations Centre",
            "role": "Operations", "org": "Department of Wildlife Conservation",
            "use_case_ids": ["UC-001"],
            "channels": [
                {"type": "sms",      "address": "+94771000004", "language": "en"},
                {"type": "whatsapp", "address": "+94771000004", "language": "en"},
            ],
            "on_call": True,
        },
    ]
    for s in stakeholders:
        await repo.upsert("stakeholders", s)

    # ── Road Signs (LED boards) ──────────────────────────────────────────────
    # 8 boards along B43 at ~55 m spacing (0.0005° lat), interleaved with cameras.
    road_signs = []
    for i in range(8):
        lat = round(6.3800 + i * 0.0005, 5)
        road_signs.append({
            "id":        f"RS-{i+1:03d}",
            "name":      f"B43 LED Board {i+1}",
            "zone_id":   "ZONE-B43",
            "road":      "B43 Yala Road",
            "km_marker": round(1.0 + i * 0.055, 2),
            "lat":       lat,
            "lng":       LNG,
            "online":    True,
        })
    # Other roads (sparse)
    road_signs += [
        {"id": "RS-009", "name": "A2 LED Board 1",        "zone_id": "ZONE-A2",  "road": "A2 Southern Highway", "km_marker": 44, "lat": 6.2815, "lng": 81.3905, "online": True},
        {"id": "RS-010", "name": "A2 LED Board 2",        "zone_id": "ZONE-A2",  "road": "A2 Southern Highway", "km_marker": 45, "lat": 6.2808, "lng": 81.3899, "online": True},
        {"id": "RS-011", "name": "Kataragama LED Board 1","zone_id": "ZONE-KTR", "road": "Kataragama Road",     "km_marker": 6,  "lat": 6.3722, "lng": 81.3312, "online": False},
    ]
    for s in road_signs:
        await repo.upsert("road_signs", s)

    # ── Rules ────────────────────────────────────────────────────────────────
    # Rules drive INCIDENTS + NOTIFICATIONS. Sign lighting is handled by the
    # spatial engine (radius mode), so rules no longer force sign states.
    rules = [
        {
            "id":           "RULE-001",
            "use_case_id":  "UC-001",
            "name":         "Single Detection – High Alert",
            "description":  "Any device detects an elephant with ≥60% confidence.",
            "priority":     1,
            "active":       True,
            "conditions": [
                {"field": "object_type", "op": "eq",  "value": "elephant"},
                {"field": "confidence",  "op": "gte", "value": 60},
            ],
            "confirmation": None,
            "actions": {
                "on_trigger": {
                    "create_incident":        True,
                    "incident_severity":      "HIGH",
                    "notify_stakeholder_ids": ["SH-001", "SH-004"],
                    "actuate_sign_ids":       [],
                    "sign_state":             "CAUTION",
                    "message_template":       "[HIGH] Possible elephant near {zone_name} ({device_name}). "
                                              "Confidence {confidence}%. Please verify. Incident {incident_id}",
                },
            },
        },
        {
            "id":           "RULE-002",
            "use_case_id":  "UC-001",
            "name":         "Dual Confirmation – Critical Alert",
            "description":  "Two or more detections in the same zone within 15 minutes.",
            "priority":     2,
            "active":       True,
            "conditions": [
                {"field": "object_type", "op": "eq",  "value": "elephant"},
                {"field": "confidence",  "op": "gte", "value": 70},
            ],
            "confirmation": {
                "required_count":  2,
                "window_seconds":  900,
                "same_zone":       True,
            },
            "actions": {
                "on_trigger": {
                    "create_incident":        True,
                    "incident_severity":      "HIGH",
                    "notify_stakeholder_ids": ["SH-001"],
                    "actuate_sign_ids":       [],
                    "sign_state":             "CAUTION",
                    "message_template":       "[HIGH] Elephant near {zone_name}. Awaiting confirmation. Incident {incident_id}",
                },
                "on_confirm": {
                    "create_incident":        True,
                    "incident_severity":      "CRITICAL",
                    "notify_stakeholder_ids": ["SH-001", "SH-002", "SH-003", "SH-004"],
                    "actuate_sign_ids":       [],
                    "sign_state":             "WARNING",
                    "message_template":       "[CRITICAL] CONFIRMED elephant on {zone_name}. Multiple detections. "
                                              "All units respond. Incident {incident_id}",
                },
            },
        },
    ]
    for r in rules:
        await repo.upsert("rules", r)

    print("[SEED] Done — Elephant Detection use case loaded "
          "(3 sensors, 11 LED boards, radius actuation).")


if __name__ == "__main__":
    import db
    async def _main():
        await db.init_db()
        await run()
    asyncio.run(_main())
