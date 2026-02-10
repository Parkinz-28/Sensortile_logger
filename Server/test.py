from datetime import datetime
import time
import json
import ssl
import sys
import paho.mqtt.client as mqtt

# HiveMQ Cloud credentials
# ⚠️ UPDATE THESE with your actual credentials from HiveMQ Console
MQTT_BROKER = "7fa53b95ab644109b299a45cabb423a6.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USERNAME = "wipro"        # ← Your HiveMQ username
MQTT_PASSWORD = "wiproMQTT1"  # ← Your HiveMQ password

TOPIC_ACCEL = "sensortile/accel"
TOPIC_MIC = "sensortile/mic"
TOPIC_STATUS = "sensortile/status"

# Track connection state
connected = False

def on_connect(client, userdata, flags, rc, properties=None):
    """Called when connected to MQTT broker."""
    global connected
    
    # MQTT v5 uses ReasonCode object, MQTT v3 uses int
    if hasattr(rc, 'value'):
        rc_value = rc.value
        rc_name = str(rc)
    else:
        rc_value = rc
        rc_name = {
            0: "Success",
            1: "Incorrect protocol version",
            2: "Invalid client identifier", 
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized"
        }.get(rc, f"Unknown ({rc})")
    
    if rc_value == 0:
        print(f"[MQTT] ✅ Connected successfully to {MQTT_BROKER}")
        connected = True
    else:
        print(f"[MQTT] ❌ Connection failed!")
        print(f"       Code: {rc_value}")
        print(f"       Reason: {rc_name}")
        print(f"       Username: '{MQTT_USERNAME}'")
        print(f"       Password: '{MQTT_PASSWORD[:3]}***'")
        connected = False

def on_disconnect(client, userdata, rc, properties=None):
    """Called when disconnected."""
    global connected
    connected = False
    print(f"[MQTT] Disconnected (rc={rc})")

def main():
    global connected
    
    print("=" * 60)
    print("  HiveMQ Connection Test")
    print("=" * 60)
    print(f"  Broker: {MQTT_BROKER}")
    print(f"  Port:   {MQTT_PORT}")
    print(f"  User:   {MQTT_USERNAME}")
    print("=" * 60)
    
    # Try MQTT v3.1.1 first (more compatible)
    # Some brokers have issues with MQTT v5 auth
    client = mqtt.Client(
        client_id=f"sensortile-test-{int(time.time())}",
        protocol=mqtt.MQTTv311  # Changed from MQTTv5
    )
    
    # Set credentials BEFORE tls_set
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    
    # Enable TLS
    client.tls_set(
        ca_certs=None,
        certfile=None,
        keyfile=None,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS,
        ciphers=None
    )
    # Optional: disable hostname verification for debugging
    # client.tls_insecure_set(True)
    
    # Set callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    
    # Connect to broker
    print(f"\n[MQTT] Connecting...")
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[MQTT] ❌ Connection exception: {e}")
        sys.exit(1)
    
    # Start network loop
    client.loop_start()
    
    # Wait for connection (with timeout)
    print("[MQTT] Waiting for connection...")
    for i in range(10):  # 10 second timeout
        if connected:
            break
        time.sleep(1)
        print(f"       ...{10-i}s remaining")
    
    if not connected:
        print("\n❌ Failed to connect after 10 seconds!")
        print("\n🔧 TROUBLESHOOTING:")
        print("   1. Check HiveMQ Console → Access Management")
        print("   2. Delete and recreate credentials")
        print("   3. Use simple password (letters + numbers only)")
        print("   4. Wait 1-2 minutes for credentials to propagate")
        client.loop_stop()
        sys.exit(1)

    print("\n✅ Connection successful! Starting data stream...\n")
    
    # Publish initial status
    status = json.dumps({"status": "online", "timestamp": datetime.now().isoformat()})
    result = client.publish(TOPIC_STATUS, status, retain=True)
    print(f"[MQTT] Status published (mid={result.mid})")

    # Dummy Data Generation Loop
    count = 0
    try:
        while True:
            if not connected:
                print("[MQTT] ⚠️ Not connected, waiting...")
                time.sleep(2)
                continue
                
            # Simulate accelerometer data
            accel_data = {
                "timestamp": datetime.now().isoformat(),
                "x": round(9.81 * (0.5 - time.time() % 1), 2),
                "y": round(9.81 * (0.5 - time.time() % 1), 2),
                "z": round(9.81 * (0.5 - time.time() % 1), 2)
            }
            client.publish(TOPIC_ACCEL, json.dumps(accel_data))

            # Simulate microphone data  
            mic_data = {
                "timestamp": datetime.now().isoformat(),
                "samples": [int(32767 * (0.5 - time.time() % 1)) for _ in range(160)]
            }
            client.publish(TOPIC_MIC, json.dumps(mic_data))
            
            count += 1
            print(f"[{count}] Accel: x={accel_data['x']:.2f} | Mic: {len(mic_data['samples'])} samples")

            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n[MQTT] Stopping dummy data generation...")
    except Exception as e:
        print(f"Error in dummy data generation: {e}")
    finally:
        # Publish offline status
        status = json.dumps({"status": "offline", "timestamp": datetime.now().isoformat()})
        client.publish(TOPIC_STATUS, status, retain=True)
        time.sleep(0.5)  # Let message send
        client.loop_stop()
        client.disconnect()
        print("[MQTT] Disconnected from broker")

# ========================== ENTRY POINT ==========================
if __name__ == "__main__":
    main()