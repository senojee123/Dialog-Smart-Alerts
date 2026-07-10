import time
import paho.mqtt.client as mqtt

BROKER_HOST = "broker.emqx.io"
BROKER_PORT = 1883
TOPIC = "methsara/mqtt-image-demo/test-jpg"
RECEIVE_FILE = "received.jpg"


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected to {BROKER_HOST} (reason_code={reason_code})")
    client.subscribe(TOPIC, qos=1)
    print(f"Subscribed to topic '{TOPIC}', waiting for images...")


def on_message(client, userdata, msg):
    filename = f"{int(time.time())}_{RECEIVE_FILE}"
    with open(filename, "wb") as f:
        f.write(msg.payload)
    print(f"Received {len(msg.payload)} bytes on '{msg.topic}' -> saved to {filename}")


def main():
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    print("Listening for images...")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        client.disconnect()


if __name__ == "__main__":
    main()