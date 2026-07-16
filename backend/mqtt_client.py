import os
import json
import asyncio
import time
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
        self.subscribe_topic = os.getenv("MQTT_SUBSCRIBE_TOPIC", "dialog/detections")
        
        # Paho MQTT Client utilizing modern API Version 2
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2, 
            client_id=os.getenv("MQTT_CLIENT_ID", "dialog-alert-service")
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        # In-memory deduplication/processing map if needed
        self.last_processed_timestamps = {}

    def start(self):
        try:
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()
            print(f"[MQTT] Started background client and connected to {self.broker_host}:{self.broker_port}")
        except Exception as e:
            print(f"[MQTT] Failed to start MQTT client: {e}")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] Stopped background client.")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"[MQTT] Connected with code {reason_code}. Subscribing to '{self.subscribe_topic}'...")
        self.client.subscribe(self.subscribe_topic, qos=1)

    def on_message(self, client, userdata, msg):
        try:
            # Parse the incoming JSON message
            payload_str = msg.payload.decode('utf-8')
            payload = json.loads(payload_str)
            
            # Fields validation
            station_id = payload.get("station_id")
            entity_id = payload.get("entity_id")
            alert = payload.get("alert")
            value = payload.get("value")
            timestamp = payload.get("timestamp")

            if not all([station_id, entity_id, alert, value is not None]):
                print(f"[MQTT] Invalid payload structure: {payload_str}")
                return

            # Normalize value to 0-100 confidence
            # (Check if value is in 0-1 scale or already 0-100)
            try:
                val_float = float(value)
                confidence = val_float * 100.0 if val_float <= 1.0 else val_float
            except (ValueError, TypeError):
                print(f"[MQTT] Invalid confidence value: {value}")
                return

            external_id = f"{station_id}_{entity_id}"
            
            # Form standard ingestion event payload
            event_body = {
                "external_id": external_id,
                "object_type": str(alert).lower(),
                "confidence": confidence,
                "captured_at": timestamp,
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
