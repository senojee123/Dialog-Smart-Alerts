import os
import json
import asyncio
import time
import uuid
from pathlib import Path
import paho.mqtt.client as mqtt

# Setup paths (matches server.py uploads)
BASE_DIR = Path(__file__).parent
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

class MQTTClientManager:
    def __init__(self, app):
        self.app = app
        self.broker_host = os.getenv("MQTT_BROKER_HOST", "broker.emqx.io")
        self.broker_port = int(os.getenv("MQTT_BROKER_PORT", 1883))
        self.topic_alerts = os.getenv("MQTT_TOPIC", "devices/modem-gateway/alerts")
        self.topic_image = os.getenv("MQTT_IMAGE_TOPIC", "devices/modem-gateway/alerts/image")
        self.topic_status = os.getenv("MQTT_STATUS_TOPIC", "devices/modem-gateway/status")
        
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
        
        # In-memory deduplication/processing map if needed
        self.last_processed_timestamps = {}

    def start(self):
        try:
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()
            print(f"[MQTT] Started background client ({self.client._client_id}) and connected to {self.broker_host}:{self.broker_port}")
        except Exception as e:
            print(f"[MQTT] Failed to start MQTT client: {e}")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] Stopped background client.")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if str(reason_code).lower() in ("0", "success", "success.") or reason_code == 0:
            print(f"[MQTT] Connected SUCCESSFUL ({reason_code}). Subscribing to topics: {self.topic_alerts}, {self.topic_image}, {self.topic_status}...")
            topics = [
                (self.topic_alerts, 1),
                (self.topic_image, 1),
                (self.topic_status, 1),
            ]
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

            # 1. Check if this is a Modem Gateway Status/Heartbeat topic
            if msg.topic == self.topic_status or msg.topic.endswith("/status"):
                device_id = payload.get("device_id") or payload.get("entity_id") or payload.get("gateway_id") or "modem-gateway"
                print(f"[MQTT STATUS] Modem Gateway heartbeat received from '{device_id}' ({msg.topic}): {payload}")
                asyncio.run_coroutine_threadsafe(
                    self.process_status_update(device_id, payload),
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
                    b64_data = raw_img
                    if "base64," in b64_data:
                        b64_data = b64_data.split("base64,")[1]
                    img_bytes = base64.b64decode(b64_data)
                    img_filename = f"img_mqtt_{entity_id}_{uuid.uuid4().hex[:6]}.jpg"
                    img_path = UPLOADS_DIR / img_filename
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    image_url = f"/uploads/{img_filename}"
                    print(f"[MQTT IMAGE] Decoded and saved Base64 image: {image_url}")
                except Exception as img_err:
                    print(f"[MQTT IMAGE] Error decoding image payload: {img_err}")

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
                self.process_mqtt_event(event_body, station_id, entity_id),
                self.app.state.loop
            )

        except json.JSONDecodeError:
            print(f"[MQTT] Failed to decode JSON payload: {msg.payload}")
        except Exception as e:
            print(f"[MQTT] Error in on_message: {e}")

    async def process_mqtt_event(self, event_body, station_id, entity_id):
        try:
            import repo
            
            # 1. Resolve device using external_id
            device = await repo.device_by_external_id(event_body["external_id"])
            
            if not device:
                # Dynamic auto-registration for multi-station support
                print(f"[MQTT] New device detected. Registering: {event_body['external_id']}...")
                device = await repo.create("devices", {
                    "name": f"MQTT Camera Trap {entity_id} (Station {station_id})",
                    "type": "camera",
                    "use_case_id": "UC-001",
                    "zone_id": "ZONE-B43", # Defaults to Yala Road Corridor
                    "lat": 6.3805,         # Default coordinates
                    "lng": 81.4800,
                    "external_id": event_body["external_id"],
                    "api_key": f"mqtt-key-{entity_id}",
                    "online": True
                })
            else:
                # Keep device state updated
                await repo.update("devices", device["id"], {"online": True})

            # 2. Ingest the event into the system's pipeline
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

    async def process_status_update(self, device_id, payload):
        try:
            import repo
            device = await repo.device_by_external_id(device_id) or await repo.get("devices", device_id)
            status_val = str(payload.get("status", "online")).lower()
            is_online = status_val not in ("offline", "disconnected", "down", "error")
            if device:
                await repo.update("devices", device["id"], {
                    "online": is_online,
                    "status": status_val,
                })
        except Exception as e:
            print(f"[MQTT STATUS] Error updating device status: {e}")
