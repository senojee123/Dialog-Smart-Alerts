import paho.mqtt.client as mqtt

BROKER_HOST = "broker.emqx.io"
BROKER_PORT = 1883
TOPIC = "methsara/mqtt-image-demo/test-jpg"  # change if you want a private/unique topic
SEND_FILE = "test.jpg"


def main():
    with open(SEND_FILE, "rb") as f:
        image_bytes = f.read()

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()

    info = client.publish(TOPIC, payload=image_bytes, qos=1)
    info.wait_for_publish()
    print(f"Published {len(image_bytes)} bytes from '{SEND_FILE}' to topic '{TOPIC}' on {BROKER_HOST}")

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()