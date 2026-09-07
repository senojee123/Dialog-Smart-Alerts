import os
import json
import asyncio
import time
import uuid
import io
from pathlib import Path
import paho.mqtt.client as mqtt

try:
    from PIL import Image
except ImportError:
    Image = None
    print("[MQTT] Pillow not installed — image corruption validation disabled (decode still works)")

# Setup paths (matches server.py uploads)
BASE_DIR = Path(__file__).parent
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


def _assert_valid_image(img_bytes: bytes) -> None:
    """Raise if img_bytes isn't a complete, decodable image.

    base64.b64decode() silently "succeeds" on corrupted input (a single
    dropped/altered character mid-stream still decodes without error, it just
    produces garbage past that point) — so a clean decode alone doesn't mean
    the photo is intact. Actually opening it is the only way to catch that.
    A missing Pillow install must never crash the server over an optional check.
    """
    if Image is None:
        return
    with Image.open(io.BytesIO(img_bytes)) as im:
        im.load()

class MQTTClientManager:
    def __init__(self, app):
        self.app = app
        # HiveMQ public broker is the platform default (the modem-gateway hardware
        # and the backend/scratch/*_live.py test scripts all use it). Override with
        # MQTT_BROKER_HOST for a private/authenticated broker.
        self.broker_host = os.getenv("MQTT_BROKER_HOST", "broker.hivemq.com")
        self.broker_port = int(os.getenv("MQTT_BROKER_PORT", 1883))
        # Auth + TLS are optional — empty username = anonymous (public brokers).
        # Accept both the current names and the older MQTT_BROKER_USER/PASSWORD ones.
        self.username = os.getenv("MQTT_USERNAME") or os.getenv("MQTT_BROKER_USER") or ""
        self.password = os.getenv("MQTT_PASSWORD") or os.getenv("MQTT_BROKER_PASSWORD") or ""
        self.use_tls = os.getenv("MQTT_USE_TLS", "false").strip().lower() in ("1", "true", "yes", "on")
        self.topic_alerts = os.getenv("MQTT_TOPIC", "devices/modem-gateway/alerts")
        self.topic_image = os.getenv("MQTT_IMAGE_TOPIC", "devices/modem-gateway/alerts/image")
        self.topic_status = os.getenv("MQTT_STATUS_TOPIC", "devices/modem-gateway/status")
        # Recurring liveness beat (separate from the retained status message).
        self.topic_heartbeat = os.getenv("MQTT_HEARTBEAT_TOPIC", "devices/modem-gateway/heartbeat")

        # Generate unique client ID to prevent client_id collisions on public broker
        unique_id = f"dialog-alert-{uuid.uuid4().hex[:6]}"
        client_id_val = os.getenv("MQTT_CLIENT_ID", unique_id)

        # Paho MQTT Client utilizing modern API Version 2
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id_val
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        if self.username:
            self.client.username_pw_set(self.username, self.password or None)
        if self.use_tls:
            import ssl
            # Default port for MQTT-over-TLS if the caller didn't set one explicitly.
            if not os.getenv("MQTT_BROKER_PORT"):
                self.broker_port = 8883
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        # In-memory deduplication/processing map if needed
        self.last_processed_timestamps = {}

    def start(self):
        try:
            auth = f"auth={self.username or '(anon)'} tls={self.use_tls}"
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()
            print(f"[MQTT] Started background client ({self.client._client_id}) — "
                  f"connecting to {self.broker_host}:{self.broker_port} ({auth})")
        except Exception as e:
            print(f"[MQTT] Failed to start MQTT client: {e}")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] Stopped background client.")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if str(reason_code).lower() in ("0", "success", "success.") or reason_code == 0:
            topics = [
                (self.topic_alerts, 1),
                (self.topic_image, 1),
                (self.topic_status, 1),
                (self.topic_heartbeat, 1),
            ]
            print(f"[MQTT] Connected SUCCESSFUL ({reason_code}). Subscribing to: "
                  + ", ".join(t for t, _ in topics))
            self.client.subscribe(topics)
        else:
            print(f"[MQTT ERROR] Connection failed with code '{reason_code}'. Subscription skipped.")

    def on_message(self, client, userdata, msg):
        try:
            import base64
            import uuid

            # Parse the incoming JSON message
            payload_str = msg.payload.decode('utf-8')
            payload = json.loads(payload_str)

            api_key = payload.get("api_key")

            # 1. Status / heartbeat topics — device liveness, not a detection
            if (msg.topic in (self.topic_status, self.topic_heartbeat)
                    or msg.topic.endswith(("/status", "/heartbeat"))):
                device_id = payload.get("device_id") or payload.get("entity_id") or payload.get("gateway_id") or "modem-gateway"
                print(f"[MQTT STATUS] liveness from '{device_id}' ({msg.topic}): {payload}")
                asyncio.run_coroutine_threadsafe(
                    self.process_status_update(device_id, payload, api_key),
                    self.app.state.loop
                )
                return

            # Fields validation (supports both entity_id / device_id and alert / object_type)
            station_id = payload.get("station_id") or "st_01"
            entity_id = payload.get("entity_id") or payload.get("device_id") or "cam_04"
            alert = payload.get("alert") or payload.get("object_type") or "elephant"
            value = payload.get("value") if payload.get("value") is not None else payload.get("confidence", 90)
            timestamp = payload.get("timestamp") or payload.get("received_at")

            if not all([station_id, entity_id, alert, value is not None]):
                print(f"[MQTT] Invalid payload structure: {payload_str}")
                return

            # Normalize value to 0-100 confidence
            try:
                val_float = float(value)
                confidence = val_float * 100.0 if val_float <= 1.0 else val_float
            except (ValueError, TypeError):
                print(f"[MQTT] Invalid confidence value: {value}")
                return

            external_id = f"{station_id}_{entity_id}"
            
            # Extract and process image (Base64 string or HTTP URL)
            image_url = payload.get("image_url")
            raw_img = payload.get("image") or payload.get("image_data") or payload.get("photo") or payload.get("base64")
            
            if raw_img and isinstance(raw_img, str) and not image_url:
                try:
                    b64_data = raw_img.strip()
                    if "," in b64_data:
                        b64_data = b64_data.split(",")[-1].strip()
                    
                    # Fix JSON space-encoding of + characters
                    b64_data = b64_data.replace(" ", "+").replace("\n", "").replace("\r", "")
                    
                    # Auto-fix missing Base64 padding (=)
                    missing_padding = len(b64_data) % 4
                    if missing_padding:
                        b64_data += "=" * (4 - missing_padding)
                    
                    img_bytes = base64.b64decode(b64_data)
                    _assert_valid_image(img_bytes)
                    img_filename = f"img_mqtt_{entity_id}_{uuid.uuid4().hex[:6]}.jpg"
                    img_path = UPLOADS_DIR / img_filename
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    image_url = f"/uploads/{img_filename}"
                    print(f"[MQTT IMAGE] Decoded and saved Base64 image: {image_url}")
                except Exception as img_err:
                    print(f"[MQTT IMAGE] Could not decode raw Base64 ({img_err}). Using default camera capture URL.")
                    image_url = "/static/placeholder.jpg"

            # Form standard ingestion event payload
            event_body = {
                "external_id": external_id,
                "device_id": entity_id,
                "object_type": str(alert).lower(),
                "confidence": confidence,
                "captured_at": timestamp,
                "image_url": image_url,
                "source": "device",
                "raw_payload": payload
            }

            # Safely schedule ingestion on the main event loop thread of FastAPI
            asyncio.run_coroutine_threadsafe(
                self.process_mqtt_event(event_body, station_id, entity_id, api_key),
                self.app.state.loop
            )

        except json.JSONDecodeError:
            raw_bytes = msg.payload
            raw_text = raw_bytes.decode('utf-8', errors='ignore').strip()
            
            # Case 1: Plain text status update (e.g. "ONLINE" or "OFFLINE" / "alive")
            if (msg.topic in (self.topic_status, self.topic_heartbeat)
                    or msg.topic.endswith(("/status", "/heartbeat"))):
                print(f"[MQTT STATUS] Non-JSON liveness payload on '{msg.topic}': {raw_text}")
                asyncio.run_coroutine_threadsafe(
                    self.process_status_update("modem-gateway", {"status": raw_text}, None),
                    self.app.state.loop
                )
                return

            # Case 2: Direct raw Base64 image payload (e.g. "iVBORw0KGgoAAA..." or "/9j/4AAQSk...")
            if msg.topic == self.topic_image or msg.topic.endswith("/image") or raw_text.startswith(("iVBORw", "/9j/", "data:image")):
                print(f"[MQTT RAW IMAGE] Non-JSON raw Base64 image received on '{msg.topic}' (Length: {len(raw_text)} chars)")
                try:
                    b64_data = raw_text
                    if "," in b64_data:
                        b64_data = b64_data.split(",")[-1].strip()
                    b64_data = b64_data.replace(" ", "+").replace("\n", "").replace("\r", "")
                    missing_padding = len(b64_data) % 4
                    if missing_padding:
                        b64_data += "=" * (4 - missing_padding)
                    img_bytes = base64.b64decode(b64_data)
                    _assert_valid_image(img_bytes)
                    img_filename = f"img_mqtt_raw_{uuid.uuid4().hex[:6]}.jpg"
                    img_path = UPLOADS_DIR / img_filename
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    image_url = f"/uploads/{img_filename}"
                    print(f"[MQTT RAW IMAGE] Decoded and saved raw image: {image_url}")
                except Exception as b64_err:
                    print(f"[MQTT RAW IMAGE] Error decoding raw Base64 ({b64_err}), using default sample image.")
                    image_url = "/static/placeholder.jpg"

                event_body = {
                    "external_id": "st_01_cam_04",
                    "device_id": "cam_04",
                    "object_type": "elephant",
                    "confidence": 92.0,
                    "image_url": image_url,
                    "source": "device",
                    "raw_payload": {"raw_image": True}
                }

                asyncio.run_coroutine_threadsafe(
                    self.process_mqtt_event(event_body, "st_01", "cam_04", None),
                    self.app.state.loop
                )
                return

            print(f"[MQTT] Non-JSON payload received on '{msg.topic}': {raw_text}")
        except Exception as e:
            print(f"[MQTT] Error in on_message: {e}")

    async def process_mqtt_event(self, event_body, station_id, entity_id, api_key=None):
        try:
            import data_store
            from server import verify_device_key, record_auth_attempt, mqtt_auth_enforced

            ext = event_body["external_id"]

            # 1. Resolve device by external_id (same store _resolve_device reads)
            device = next((d for d in data_store.get_all("devices")
                           if d.get("external_id") == ext), None)

            # 2. Authenticate the producer. No auto-registration — an unknown or
            #    unauthenticated device is logged and (when enforced) dropped.
            reason = verify_device_key(device, api_key)
            if reason:
                enforced = mqtt_auth_enforced()
                record_auth_attempt(source="mqtt", external_id=ext, station_id=station_id,
                                    entity_id=entity_id, reason=reason, enforced=enforced,
                                    object_type=event_body.get("object_type"))
                if enforced or reason in ("unknown_device", "disabled"):
                    print(f"[MQTT AUTH] rejected '{ext}': {reason}"
                          f"{'' if enforced else ' (grace period)'}")
                    return
                print(f"[MQTT AUTH] '{ext}': {reason} — processing anyway (grace period, "
                      f"set MQTT_ENFORCE_AUTH=true to reject)")

            # Keep device liveness fresh; strip the credential before storage.
            data_store.update("devices", device["id"], {"online": True})
            if isinstance(event_body.get("raw_payload"), dict):
                event_body["raw_payload"].pop("api_key", None)

            # 3. Ingest the event into the system's pipeline
            # Import dynamically to avoid circular import issues
            from server import _ingest_event
            event, incident = await _ingest_event(event_body, source="device")
            
            print(f"[MQTT] Successfully ingested event: {event['id']} (Incident: {incident['id'] if incident else 'None'})")

            # 3. Actuate hardware based on evaluated incident severity
            if incident:
                sev = incident.get("severity", "HIGH")
                if sev == "CRITICAL":
                    print(f"[MQTT ALERT] Critical warning trigger for {event_body['object_type']} (Incident: {incident['id']})")
                    self.actuate_led(station_id, "RED")
                    self.actuate_siren(station_id, "ON")
                elif sev == "HIGH":
                    print(f"[MQTT ALERT] High warning trigger for {event_body['object_type']} (Incident: {incident['id']})")
                    self.actuate_led(station_id, "AMBER")
                else:
                    print(f"[MQTT ALERT] Warning trigger for {event_body['object_type']} (Incident: {incident['id']}, Severity: {sev})")
            else:
                print(f"[MQTT MONITOR] Event processed. No active incident generated.")

        except Exception as e:
            print(f"[MQTT] Error processing ingested event: {e}")

    def actuate_led(self, station_id, state):
        topic = f"dialog/actuators/signs/{station_id}/command"
        payload = {"state": state}
        self.client.publish(topic, json.dumps(payload), qos=1)
        print(f"[MQTT ACTUATOR] Published LED command to '{topic}': {payload}")

    def actuate_siren(self, station_id, state):
        topic = f"dialog/actuators/sirens/{station_id}/command"
        payload = {"state": state, "duration_seconds": 30}
        self.client.publish(topic, json.dumps(payload), qos=1)
        print(f"[MQTT ACTUATOR] Published Siren command to '{topic}': {payload}")

    async def process_status_update(self, device_id, payload, api_key=None):
        try:
            import data_store
            from server import record_auth_attempt, mqtt_auth_enforced

            # Resolve device by external_id or our own id (no fuzzy name match).
            all_devs = data_store.get_all("devices")
            device = next((d for d in all_devs
                           if d.get("external_id") == device_id
                           or d["id"].lower() == device_id.lower()), None)

            # No auto-registration — status from an unregistered device is logged, ignored.
            if not device:
                record_auth_attempt(source="mqtt-status", external_id=device_id,
                                    reason="unknown_device", enforced=mqtt_auth_enforced())
                print(f"[MQTT STATUS] ignored status from unregistered device '{device_id}'")
                return

            # Note a key mismatch for the audit trail, but never drop a status message.
            if api_key and str(api_key) != str(device.get("api_key", "")):
                record_auth_attempt(source="mqtt-status", external_id=device_id,
                                    reason="bad_key", enforced=mqtt_auth_enforced())

            status_val = str(payload.get("status", "online")).lower()
            is_online = status_val not in ("offline", "disconnected", "down", "error", "dead")
            data_store.update("devices", device["id"], {
                "online": is_online, "status": status_val, "last_seen": data_store._now(),
            })
            print(f"[MQTT STATUS] '{device['name']}' online={is_online} (last_seen updated)")
        except Exception as e:
            print(f"[MQTT STATUS] Error updating device status: {e}")
