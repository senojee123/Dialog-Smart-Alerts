"""
Sends a real test image over MQTT to the LIVE deployed Dialog Smart Alerts
backend (Railway), exactly as the modem-gateway hardware would (bare base64
bytes on the raw image topic -- no JSON wrapper).

Fully portable: the test image itself is pulled from the deployed app's own
/uploads/elephant_warning.jpg at runtime, so this script has no dependency on
the local repo or any local file -- copy it to any machine with Python +
paho-mqtt installed and it works.

Flow:
  1. Download the canonical elephant_warning.jpg from the deployed app
  2. Publish it as raw base64 to the HiveMQ broker's image topic
  3. Poll the deployed REST API to confirm the backend decoded + ingested it
  4. Print the live dashboard URL to go look at it

Usage:
  pip install paho-mqtt
  python backend/scratch/send_test_image_live.py
"""

import base64
import json
import sys
import time
import urllib.request

import paho.mqtt.client as mqtt

APP_URL = "https://dialog-smart-alerts-production.up.railway.app"
TEST_IMAGE_URL = f"{APP_URL}/uploads/elephant_warning.jpg"

BROKER_HOST = "broker.hivemq.com"
BROKER_PORT = 1883
IMAGE_TOPIC = "devices/modem-gateway/alerts/image"

WAIT_AFTER_PUBLISH = 5  # seconds, gives the backend time to ingest + enrich


def http_get_json(url):
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_test_image():
    print(f"Fetching test image from deployed app: {TEST_IMAGE_URL}")
    with urllib.request.urlopen(TEST_IMAGE_URL, timeout=15) as resp:
        img_bytes = resp.read()
    print(f"  Got {len(img_bytes)} bytes")
    return img_bytes


def publish_image(img_bytes):
    b64_text = base64.b64encode(img_bytes).decode("ascii")

    connected = {"ok": False}
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"dsa-live-image-tx-{int(time.time())}",
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

    info = client.publish(IMAGE_TOPIC, b64_text.encode("ascii"), qos=1)
    info.wait_for_publish(timeout=5)
    client.loop_stop()
    client.disconnect()

    print(f"Published {len(b64_text)} base64 chars to '{IMAGE_TOPIC}' on {BROKER_HOST}:{BROKER_PORT}")
    return True


def verify_ingested():
    print(f"Waiting {WAIT_AFTER_PUBLISH}s for the deployed backend to ingest + enrich...")
    time.sleep(WAIT_AFTER_PUBLISH)

    try:
        events = http_get_json(f"{APP_URL}/api/events")
    except Exception as e:
        print(f"[WARN] Could not reach deployed API to verify: {e}")
        return

    # The raw-image ingestion path in mqtt_client.py always tags this event
    # st_01/cam_04/elephant -- match on that + a recently-created image URL.
    candidates = [
        e for e in events
        if e.get("object_type") == "elephant" and "img_mqtt_raw_" in (e.get("image_url") or "")
    ]
    if not candidates:
        print("[FAIL] No matching elephant event with an mqtt-raw image found via /api/events.")
        print("       Check the deployed server logs / MQTT_BROKER_HOST env var on Railway.")
        return

    ev = sorted(candidates, key=lambda e: e.get("received_at", ""))[-1]
    print(f"[PASS] Backend ingested the image: event={ev['id']} image_url={ev.get('image_url')}")
    print(f"       Full image: {APP_URL}{ev.get('image_url')}")


def main():
    img_bytes = fetch_test_image()
    if not publish_image(img_bytes):
        sys.exit(1)
    verify_ingested()
    print()
    print(f"Go look at the live dashboard: {APP_URL}/")
    print("(This creates a real elephant/HIGH incident on st_01/cam_04 and may")
    print(" trigger real SMS/actuator commands on whatever hardware is subscribed.)")


if __name__ == "__main__":
    main()
