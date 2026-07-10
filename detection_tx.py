"""
detection_tx.py — One-shot detection publisher (same style as image_tx.py)
===========================================================================
Publishes a single JSON detection event to the server's MQTT detection topic.
The server processes it through the rule engine and broadcasts the result via
SSE, so the Live Incidents dashboard updates instantly.

Usage
-----
  python detection_tx.py                   # defaults: elephant 94%
  python detection_tx.py lion 0.85         # custom alert + confidence
  python detection_tx.py elephant 0.70     # low-confidence (no alarm)

Environment overrides (same as the server):
  MQTT_BROKER_HOST      default: broker.hivemq.com
  MQTT_BROKER_PORT      default: 1883
  MQTT_SUBSCRIBE_TOPIC  default: dialog/detections
"""

import json
import os
import sys
import time

# ── Config (mirrors mqtt_client.py defaults) ──────────────────────────────────
BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "broker.emqx.io")
BROKER_PORT  = int(os.getenv("MQTT_BROKER_PORT", "1883"))
TOPIC        = os.getenv("MQTT_SUBSCRIBE_TOPIC", "dialog/detections")

# ── Detection payload — all overridable via CLI args ──────────────────────────
# Usage: python detection_tx.py [alert] [value] [station_id] [entity_id]
ALERT      = sys.argv[1] if len(sys.argv) > 1 else "elephant"
VALUE      = float(sys.argv[2]) if len(sys.argv) > 2 else 0.94
STATION_ID = sys.argv[3] if len(sys.argv) > 3 else "st_01"
ENTITY_ID  = sys.argv[4] if len(sys.argv) > 4 else "cam_04"


def main():
    payload = {
        "station_id": STATION_ID,
        "entity_id":  ENTITY_ID,
        "alert":      ALERT,
        "value":      VALUE,
        "timestamp":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    payload_json = json.dumps(payload)

    import paho.mqtt.publish as publish
    
    print(f"Broker : {BROKER_HOST}:{BROKER_PORT}")
    print(f"Topic  : {TOPIC}")
    print(f"Payload: {payload_json}")
    print()

    # qos=0 is fire-and-forget; it doesn't wait for a round-trip acknowledgement,
    # making the script execute instantly.
    start_time = time.perf_counter()
    publish.single(
        TOPIC,
        payload=payload_json,
        hostname=BROKER_HOST,
        port=BROKER_PORT,
        qos=0
    )
    duration = time.perf_counter() - start_time

    print(f"Published successfully to topic '{TOPIC}' in {duration:.4f} seconds!")
    print(f"Watch the Live Incidents page -- it will update within ~5 seconds.")


if __name__ == "__main__":
    main()
