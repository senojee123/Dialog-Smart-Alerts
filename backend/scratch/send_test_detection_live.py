"""
Flow:
  1. Load the image (your file, or the deployed app's reference photo)
  2. Base64-encode it and bundle it into ONE JSON payload with station_id,
     entity_id, alert (object type), value (confidence), timestamp
  3. Publish that JSON to the HiveMQ broker's *alerts* topic (not the
     image-only topic -- that's what makes this "path 1")
  4. Poll the deployed REST API to confirm the backend ingested it with the
     object_type/confidence you actually sent
  5. Print the live dashboard URL to go look at it

Usage:
  pip install paho-mqtt
  python send_test_detection_live.py
  python send_test_detection_live.py path/to/photo.jpg
  python send_test_detection_live.py path/to/photo.jpg --alert person --confidence 0.75
  python send_test_detection_live.py --alert vehicle --confidence 0.60
"""

import argparse
import base64
import json
import sys
import time
import urllib.request

import paho.mqtt.client as mqtt

APP_URL = "https://dialog-smart-alerts-production.up.railway.app"
DEFAULT_TEST_IMAGE_URL = f"{APP_URL}/uploads/elephant_warning.jpg"

BROKER_HOST = "broker.hivemq.com"
BROKER_PORT = 1883
ALERTS_TOPIC = "devices/modem-gateway/alerts"  # JSON path -- NOT the image-only topic

WAIT_AFTER_PUBLISH = 5  # seconds, gives the backend time to ingest + enrich


def http_get_json(url):
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read())


def load_image(path):
    if path:
        print(f"Reading local image: {path}")
        with open(path, "rb") as f:
            img_bytes = f.read()
    else:
        print(f"No image given -- fetching reference image from deployed app: {DEFAULT_TEST_IMAGE_URL}")
        with urllib.request.urlopen(DEFAULT_TEST_IMAGE_URL, timeout=15) as resp:
            img_bytes = resp.read()
    print(f"  Got {len(img_bytes)} bytes")
    return img_bytes


def publish_detection(img_bytes, station_id, entity_id, alert, confidence):
    b64_text = base64.b64encode(img_bytes).decode("ascii")
    payload = {
        "station_id": station_id,
        "entity_id": entity_id,
        "alert": alert,
        "value": confidence,
        "image": b64_text,
    }

    connected = {"ok": False}
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"dsa-live-detect-tx-{int(time.time())}",
    )
    client.on_connect = lambda c, u, f, rc, p: connected.__setitem__("ok", True)
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    client.loop_start()

    deadline = time.time() + 10
    while not connected["ok"] and time.time() < deadline:
        time.sleep(0.2)
    if not connected["ok"]:
        print(f"[ERROR] Could not connect to {BROKER_HOST}:{BROKER_PORT}")
        client.loop_stop()
        return False

    info = client.publish(ALERTS_TOPIC, json.dumps(payload), qos=1)
    info.wait_for_publish(timeout=5)
    client.loop_stop()
    client.disconnect()

    print(f"Published detection (alert={alert}, confidence={confidence}, "
          f"station={station_id}, entity={entity_id}) to '{ALERTS_TOPIC}' on {BROKER_HOST}:{BROKER_PORT}")
    return True


def verify_ingested(alert, confidence):
    print(f"Waiting {WAIT_AFTER_PUBLISH}s for the deployed backend to ingest + enrich...")
    time.sleep(WAIT_AFTER_PUBLISH)

    try:
        events = http_get_json(f"{APP_URL}/api/events")
    except Exception as e:
        print(f"[WARN] Could not reach deployed API to verify: {e}")
        return

    want_conf = confidence * 100.0 if confidence <= 1.0 else confidence
    candidates = [
        e for e in events
        if e.get("object_type") == alert.lower()
        and abs(float(e.get("confidence", -999)) - want_conf) < 0.5
        and e.get("image_url")
    ]
    if not candidates:
        print(f"[FAIL] No matching '{alert}' event at {want_conf}% confidence found via /api/events.")
        print("       Check the deployed server logs / MQTT_BROKER_HOST env var on Railway.")
        return

    ev = sorted(candidates, key=lambda e: e.get("received_at", ""))[-1]
    print(f"[PASS] Backend ingested with the REAL metadata you sent (not hardcoded):")
    print(f"       event={ev['id']} object_type={ev.get('object_type')} confidence={ev.get('confidence')}%")
    print(f"       image={APP_URL}{ev.get('image_url')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_path", nargs="?", default=None,
                         help="Local image file to send. Omit to use the deployed app's reference photo.")
    parser.add_argument("--alert", default="elephant", help="Object type / alert label (default: elephant)")
    parser.add_argument("--confidence", type=float, default=0.87,
                         help="Confidence as 0-1 or 0-100 (default: 0.87)")
    parser.add_argument("--station-id", default="st_01")
    parser.add_argument("--entity-id", default="cam_04")
    args = parser.parse_args()

    img_bytes = load_image(args.image_path)
    if not publish_detection(img_bytes, args.station_id, args.entity_id, args.alert, args.confidence):
        sys.exit(1)
    verify_ingested(args.alert, args.confidence)
    print()
    print(f"Go look at the live dashboard: {APP_URL}/")


if __name__ == "__main__":
    main()
