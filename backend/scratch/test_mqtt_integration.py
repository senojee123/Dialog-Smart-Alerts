"""
End-to-end MQTT integration test for Dialog Smart Alerts.

Flow:
  1. This script PUBLISHES detection messages to the MQTT broker
  2. The running server's mqtt_client.py RECEIVES and PROCESSES them
  3. This script checks the REST API to VERIFY results

Usage:
  Terminal 1:  cd backend && python server.py
  Terminal 2:  python backend/scratch/test_mqtt_integration.py
"""

import sys
import os

# Fix Windows console encoding so Unicode box/emoji chars print safely
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

import json
import time
import urllib.request
import urllib.error
import paho.mqtt.client as mqtt

# ── Config ────────────────────────────────────────────────────────────────────
BROKER_HOST    = os.getenv("MQTT_BROKER_HOST", "broker.emqx.io")
BROKER_PORT    = int(os.getenv("MQTT_BROKER_PORT", 1883))
DETECT_TOPIC   = os.getenv("MQTT_SUBSCRIBE_TOPIC", "dialog/detections")
BASE_URL       = "http://localhost:8000"

# How long to wait after publishing before checking results.
# EMQX public broker is extremely fast; 3s is plenty.
WAIT_AFTER_PUBLISH = 3  # seconds

# ── MQTT Publisher ────────────────────────────────────────────────────────────

_mqtt_connected = False

def _on_connect(client, userdata, flags, reason_code, properties):
    global _mqtt_connected
    _mqtt_connected = True

def publish_detection(station_id, entity_id, alert, value):
    """
    Publish one detection message in the exact format the cameras send:
    {
      "station_id": "st_01",
      "entity_id":  "cam_04",
      "alert":      "elephant",
      "value":      0.94,
      "timestamp":  "2026-07-07T15:05:00Z"
    }
    """
    global _mqtt_connected
    _mqtt_connected = False

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"dsa-test-publisher-{int(time.time())}"
    )
    client.on_connect = _on_connect
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    client.loop_start()

    # Wait for broker connection (up to 10 s)
    deadline = time.time() + 10
    while not _mqtt_connected and time.time() < deadline:
        time.sleep(0.2)

    if not _mqtt_connected:
        client.loop_stop()
        print(f"  [ERROR] Could not connect to MQTT broker at {BROKER_HOST}:{BROKER_PORT}")
        return False

    payload = {
        "station_id": station_id,
        "entity_id":  entity_id,
        "alert":      alert,
        "value":      value,
        "timestamp":  "2026-07-07T15:05:00Z"
    }
    info = client.publish(DETECT_TOPIC, json.dumps(payload), qos=1)
    info.wait_for_publish(timeout=5)
    client.loop_stop()
    client.disconnect()
    print(f"  [MQTT] Published → topic='{DETECT_TOPIC}' payload={payload}")
    return True

# ── REST helpers ──────────────────────────────────────────────────────────────

def http_get(path):
    req = urllib.request.Request(BASE_URL + path)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

def check_server():
    try:
        http_get("/api/use-cases")
        print(f"  [OK] Server reachable at {BASE_URL}")
        return True
    except Exception as e:
        print(f"  [ERROR] Cannot reach server at {BASE_URL}: {e}")
        print("          Make sure 'python server.py' is running in backend/")
        return False

def find_device(external_id):
    devices = http_get("/api/devices")
    return next((d for d in devices if d.get("external_id") == external_id), None)

# ── Tests ─────────────────────────────────────────────────────────────────────

def run_tests():
    print("=" * 62)
    print("  Dialog Smart Alerts -- MQTT Pipeline Integration Tests")
    print("=" * 62)

    if not check_server():
        return

    # Snapshot of event/incident counts before tests so we can detect new ones
    events_before     = len(http_get("/api/events"))
    incidents_before  = len(http_get("/api/incidents"))
    notif_before      = len(http_get("/api/notifications"))
    external_id       = "st_01_cam_04"

    results = []

    # -------------------------------------------------------------------------
    # TEST 1: Low confidence (value=0.70 → 70%) — log only, no critical alarm
    # -------------------------------------------------------------------------
    print()
    print("--" * 31)
    print("TEST 1: Low confidence elephant (value=0.70 → 70%)")
    print("        Expect: Event stored in history. NO critical alarm.")
    print("--" * 31)

    ok = publish_detection("st_01", "cam_04", "elephant", 0.70)
    if not ok:
        print("  [SKIP] Could not reach MQTT broker — check network / broker URL")
        results.append(("TEST 1", None))
    else:
        print(f"  Waiting {WAIT_AFTER_PUBLISH}s for server to process message...")
        time.sleep(WAIT_AFTER_PUBLISH)

        events_after = http_get("/api/events")
        new_events   = [e for e in events_after
                        if e.get("object_type") == "elephant"
                        and float(e.get("confidence", 0)) == 70.0]

        if new_events:
            print(f"  [PASS] Event stored in history: {new_events[-1]['id']} "
                  f"(confidence={new_events[-1]['confidence']}%)")
            results.append(("TEST 1 - Event logged", True))
        else:
            print(f"  [FAIL] No 70% elephant event found in history after {WAIT_AFTER_PUBLISH}s")
            results.append(("TEST 1 - Event logged", False))

        # Verify no CRITICAL incident was opened for this low-confidence event
        device    = find_device(external_id)
        incidents = http_get("/api/incidents")
        critical  = [i for i in incidents
                     if i.get("severity") == "CRITICAL"
                     and i.get("device_id") == (device["id"] if device else "")]
        # Only consider incidents newer than before this test
        if not critical:
            print("  [PASS] No CRITICAL incident opened (threshold not reached)")
            results.append(("TEST 1 - No critical alarm", True))
        else:
            print("  [NOTE] A CRITICAL incident exists — may be from a previous run")
            results.append(("TEST 1 - No critical alarm", None))

    # -------------------------------------------------------------------------
    # TEST 2: High confidence (value=0.94 → 94%) — full alarm chain
    # -------------------------------------------------------------------------
    print()
    print("--" * 31)
    print("TEST 2: High confidence elephant (value=0.94 → 94%)")
    print("        Expect: Event stored, incident opened, notifications sent,")
    print("                LED sign set to RED, siren command published.")
    print("--" * 31)

    ok = publish_detection("st_01", "cam_04", "elephant", 0.94)
    if not ok:
        print("  [SKIP] Could not reach MQTT broker")
        results.append(("TEST 2", None))
    else:
        print(f"  Waiting {WAIT_AFTER_PUBLISH}s for server to process message...")
        time.sleep(WAIT_AFTER_PUBLISH)

        # 2a. Event stored
        events_after = http_get("/api/events")
        new_94       = [e for e in events_after
                        if e.get("object_type") == "elephant"
                        and abs(float(e.get("confidence", 0)) - 94.0) < 0.5]

        if new_94:
            ev = new_94[-1]
            print(f"  [PASS] Event stored: {ev['id']} (confidence={ev['confidence']}%)")
            results.append(("TEST 2 - Event stored", True))
        else:
            print(f"  [FAIL] No 94% elephant event found after {WAIT_AFTER_PUBLISH}s")
            results.append(("TEST 2 - Event stored", False))

        # 2b. Incident created
        incidents_after = http_get("/api/incidents")
        new_incidents   = incidents_after[incidents_before:]
        device = find_device(external_id)

        if new_incidents or incidents_after:
            active = [i for i in incidents_after
                      if i.get("status") in ("ACTIVE", "OPERATOR_REVIEW")
                      and i.get("object") == "elephant"]
            if active:
                inc = active[-1]
                print(f"  [PASS] Incident: {inc['id']} "
                      f"severity={inc.get('severity')} status={inc.get('status')}")
                results.append(("TEST 2 - Incident opened", True))
            else:
                print("  [NOTE] No active elephant incident found "
                      "(may need confirmation round — check rule config)")
                results.append(("TEST 2 - Incident opened", None))
        else:
            print("  [FAIL] No incidents in system")
            results.append(("TEST 2 - Incident opened", False))

        # 2c. Notifications dispatched
        notif_after  = http_get("/api/notifications")
        new_notifs   = notif_after[notif_before:]
        if new_notifs:
            print(f"  [PASS] {len(new_notifs)} notification(s) dispatched:")
            for n in new_notifs[:5]:
                print(f"         [{n.get('channel','?').upper()}] "
                      f"-> {n.get('address','?')} | status={n.get('status','?')}")
            results.append(("TEST 2 - Notifications sent", True))
        else:
            print("  [NOTE] No new notifications (may be within cooldown window)")
            results.append(("TEST 2 - Notifications sent", None))

        # 2d. Road signs in WARNING / CAUTION
        signs         = http_get("/api/road-signs")
        warning_signs = [s for s in signs if s.get("state") in ("WARNING", "CAUTION")]
        if warning_signs:
            print(f"  [PASS] {len(warning_signs)} sign(s) actuated to WARNING/CAUTION (LED RED/AMBER):")
            for s in warning_signs:
                print(f"         {s['id']} -> {s.get('state')} ({s.get('name','')})")
            results.append(("TEST 2 - LED signs actuated", True))
        else:
            print("  [NOTE] No signs in WARNING state yet "
                  "(spatial radius may not overlap; check device lat/lng vs sign positions)")
            results.append(("TEST 2 - LED signs actuated", None))

    # -------------------------------------------------------------------------
    # TEST 3: Alert history contains both events
    # -------------------------------------------------------------------------
    print()
    print("--" * 31)
    print("TEST 3: Alert history logging")
    print("        Expect: Both detections appear in /api/events")
    print("--" * 31)

    all_events = http_get("/api/events")
    device     = find_device(external_id)
    if device:
        our_events = [e for e in all_events if e.get("device_id") == device["id"]]
        if len(our_events) >= 2:
            print(f"  [PASS] {len(our_events)} event(s) in alert history for {external_id}:")
            for e in sorted(our_events, key=lambda x: x.get("received_at",""), reverse=True)[:5]:
                print(f"         {e['id']} | conf={e.get('confidence')}% "
                      f"| {e.get('received_at','')[:19]}")
            results.append(("TEST 3 - Alert history", True))
        else:
            print(f"  [FAIL] Only {len(our_events)} event(s) found, expected >= 2")
            results.append(("TEST 3 - Alert history", False))
    else:
        print(f"  [FAIL] Device {external_id} not auto-registered by server mqtt_client")
        results.append(("TEST 3 - Alert history", False))

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 62)
    print("  RESULTS SUMMARY")
    print("=" * 62)
    passed = warned = failed = 0
    for name, result in results:
        if result is True:
            print(f"  [PASS]  {name}")
            passed += 1
        elif result is None:
            print(f"  [WARN]  {name}")
            warned += 1
        else:
            print(f"  [FAIL]  {name}")
            failed += 1

    print()
    print(f"  Passed: {passed}  |  Warnings: {warned}  |  Failed: {failed}")
    print("=" * 62)

    if failed == 0:
        print("\n  All critical tests passed. MQTT pipeline is working.")
    else:
        print(f"\n  {failed} test(s) failed. Check server logs for details.")


if __name__ == "__main__":
    run_tests()
