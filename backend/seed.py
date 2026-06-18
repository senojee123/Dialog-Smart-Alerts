"""
Seed the data store with the Elephant Detection use case.
Runs once on server startup when data/ is empty.
"""

import data_store


def run():
    if data_store.count("use_cases") > 0:
        return  # Already seeded

    print("[SEED] Initialising Elephant Detection use case...")

    # ── Use Case ────────────────────────────────────────────────────────────
    data_store.upsert("use_cases", {
        "id":          "UC-001",
        "name":        "Elephant Detection – Road Corridor",
        "description": "Detect elephants near road corridors and alert stakeholders. "
                       "Triggers road-sign warnings and notifies rangers, traffic control, and police.",
        "active":      True,
        "icon":        "elephant",
        "color":       "#D92D20",
    })

    # ── Zones ───────────────────────────────────────────────────────────────
    zones = [
        {"id": "ZONE-B43-N", "name": "B43 Yala Road – North",    "use_case_id": "UC-001", "road": "B43", "lat": 6.4050, "lng": 81.4800},
        {"id": "ZONE-B43-S", "name": "B43 Yala Road – South",    "use_case_id": "UC-001", "road": "B43", "lat": 6.3200, "lng": 81.4600},
        {"id": "ZONE-A2",    "name": "A2 Southern Highway",       "use_case_id": "UC-001", "road": "A2",  "lat": 6.2800, "lng": 81.3900},
        {"id": "ZONE-KTR",   "name": "Kataragama Road",           "use_case_id": "UC-001", "road": "KTR", "lat": 6.3700, "lng": 81.3300},
        {"id": "ZONE-TISSA", "name": "Tissa–Yala Road",           "use_case_id": "UC-001", "road": "TYR", "lat": 6.2900, "lng": 81.2500},
    ]
    for z in zones:
        data_store.upsert("zones", z)

    # ── Devices (Camera Traps) ──────────────────────────────────────────────
    devices = [
        {"id": "DEV-001", "name": "Camera Trap – B43 North Gate",  "type": "camera", "zone_id": "ZONE-B43-N", "use_case_id": "UC-001", "lat": 6.4012, "lng": 81.4820, "api_key": "dev-key-001", "online": True},
        {"id": "DEV-002", "name": "Camera Trap – B43 South Gate",  "type": "camera", "zone_id": "ZONE-B43-S", "use_case_id": "UC-001", "lat": 6.3268, "lng": 81.4601, "api_key": "dev-key-002", "online": True},
        {"id": "DEV-003", "name": "Thermal Sensor – A2 Junction",  "type": "thermal","zone_id": "ZONE-A2",    "use_case_id": "UC-001", "lat": 6.2812, "lng": 81.3902, "api_key": "dev-key-003", "online": True},
        {"id": "DEV-004", "name": "Camera Trap – Kataragama Rd",   "type": "camera", "zone_id": "ZONE-KTR",   "use_case_id": "UC-001", "lat": 6.3720, "lng": 81.3310, "api_key": "dev-key-004", "online": False},
        {"id": "DEV-005", "name": "Camera Trap – Tissa Road",      "type": "camera", "zone_id": "ZONE-TISSA", "use_case_id": "UC-001", "lat": 6.2920, "lng": 81.2490, "api_key": "dev-key-005", "online": True},
    ]
    for d in devices:
        data_store.upsert("devices", d)

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
        data_store.upsert("stakeholders", s)

    # ── Road Signs ──────────────────────────────────────────────────────────
    road_signs = [
        {"id": "RS-001", "name": "B43 North – Board 1",  "zone_id": "ZONE-B43-N", "road": "B43 Yala Road",       "km_marker": 12, "lat": 6.4020, "lng": 81.4810, "online": True},
        {"id": "RS-002", "name": "B43 North – Board 2",  "zone_id": "ZONE-B43-N", "road": "B43 Yala Road",       "km_marker": 15, "lat": 6.3900, "lng": 81.4750, "online": True},
        {"id": "RS-003", "name": "B43 South – Board 1",  "zone_id": "ZONE-B43-S", "road": "B43 Yala Road",       "km_marker": 28, "lat": 6.3300, "lng": 81.4620, "online": True},
        {"id": "RS-004", "name": "A2 Junction – Board 1","zone_id": "ZONE-A2",    "road": "A2 Southern Highway", "km_marker": 44, "lat": 6.2850, "lng": 81.3950, "online": True},
        {"id": "RS-005", "name": "A2 Junction – Board 2","zone_id": "ZONE-A2",    "road": "A2 Southern Highway", "km_marker": 47, "lat": 6.2780, "lng": 81.3870, "online": True},
        {"id": "RS-006", "name": "Kataragama – Board 1", "zone_id": "ZONE-KTR",   "road": "Kataragama Road",     "km_marker": 6,  "lat": 6.3710, "lng": 81.3320, "online": True},
        {"id": "RS-007", "name": "Tissa Road – Board 1", "zone_id": "ZONE-TISSA", "road": "Tissa–Yala Road",     "km_marker": 3,  "lat": 6.2930, "lng": 81.2510, "online": True},
        {"id": "RS-008", "name": "Tissa Road – Board 2", "zone_id": "ZONE-TISSA", "road": "Tissa–Yala Road",     "km_marker": 7,  "lat": 6.2910, "lng": 81.2480, "online": False},
    ]
    for s in road_signs:
        data_store.upsert("road_signs", s)

    # ── Rules ────────────────────────────────────────────────────────────────
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
                    "message_template":       "[HIGH] Possible elephant detected near {zone_name} by {device_name}. "
                                              "Confidence: {confidence}%. Please verify. Incident: {incident_id}",
                },
            },
        },
        {
            "id":           "RULE-002",
            "use_case_id":  "UC-001",
            "name":         "Dual Confirmation – Critical Alert",
            "description":  "Two or more devices in the same zone detect an elephant within 15 minutes.",
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
                    "message_template":       "[HIGH] Elephant detected near {zone_name}. Awaiting confirmation. Incident: {incident_id}",
                },
                "on_confirm": {
                    "create_incident":        True,
                    "incident_severity":      "CRITICAL",
                    "notify_stakeholder_ids": ["SH-001", "SH-002", "SH-003", "SH-004"],
                    "actuate_sign_ids":       ["RS-001", "RS-002", "RS-003"],
                    "sign_state":             "WARNING",
                    "message_template":       "[CRITICAL] CONFIRMED: Elephant on {zone_name}. Multiple detections. "
                                              "All units respond. Road signs activated. Incident: {incident_id}",
                },
            },
        },
    ]
    for r in rules:
        data_store.upsert("rules", r)

    print("[SEED] Done — Elephant Detection use case loaded.")


if __name__ == "__main__":
    run()
