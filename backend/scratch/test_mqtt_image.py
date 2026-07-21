"""
Publishes a test image to the MQTT raw-image topic exactly as the modem-gateway
would (bare base64 bytes, no JSON wrapper) -- lets you test the image decode +
corruption-detection path without needing the physical gateway hardware.

Usage:
  python backend/scratch/test_mqtt_image.py                  # clean synthetic image
  python backend/scratch/test_mqtt_image.py --corrupt        # deliberately drop
                                                               # 1 char mid-stream,
                                                               # should now be
                                                               # rejected + fall
                                                               # back to the
                                                               # placeholder instead
                                                               # of silently saving
                                                               # a broken file
  python backend/scratch/test_mqtt_image.py path/to/photo.jpg [--corrupt]
"""

import base64
import io
import os
import sys
import time

import paho.mqtt.client as mqtt

BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "broker.emqx.io")
BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", 1883))
IMAGE_TOPIC = os.getenv("MQTT_IMAGE_TOPIC", "devices/modem-gateway/alerts/image")


def _build_test_image_bytes():
    """A small real JPEG generated in memory, so this script needs no external file."""
    from PIL import Image
    im = Image.new("RGB", (200, 200), color=(200, 30, 30))
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    return buf.getvalue()


def _corrupt(b64_text: str) -> str:
    """Drop one character mid-stream -- the exact failure mode diagnosed earlier."""
    mid = len(b64_text) // 2
    return b64_text[:mid] + b64_text[mid + 1:]


def main():
    args = sys.argv[1:]
    corrupt = "--corrupt" in args
    file_args = [a for a in args if not a.startswith("--")]

    if file_args:
        with open(file_args[0], "rb") as f:
            img_bytes = f.read()
        print(f"Using real image file: {file_args[0]} ({len(img_bytes)} bytes)")
    else:
        img_bytes = _build_test_image_bytes()
        print(f"Generated a synthetic test JPEG ({len(img_bytes)} bytes)")

    b64_text = base64.b64encode(img_bytes).decode("ascii")
    if corrupt:
        b64_text = _corrupt(b64_text)
        print("Deliberately corrupted the payload (dropped 1 char mid-stream)")

    connected = {"ok": False}
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"dsa-test-image-tx-{int(time.time())}",
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
        return

    info = client.publish(IMAGE_TOPIC, b64_text.encode("ascii"), qos=1)
    info.wait_for_publish(timeout=5)
    client.loop_stop()
    client.disconnect()

    print(f"Published {len(b64_text)} base64 chars to '{IMAGE_TOPIC}' on {BROKER_HOST}:{BROKER_PORT}")
    print()
    print("Watch the backend logs for one of:")
    print("  [MQTT RAW IMAGE] Decoded and saved raw image: ...   <- accepted")
    print("  [MQTT RAW IMAGE] Error decoding raw Base64 (...)    <- rejected (expected with --corrupt)")
    print()
    print("This will also create a real incident (elephant, HIGH severity, st_01/cam_04)")
    print("and may trigger a real SMS/actuator command on whatever backend is subscribed.")


if __name__ == "__main__":
    main()
