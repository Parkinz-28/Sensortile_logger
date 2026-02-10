#!/usr/bin/env python3
"""
SensorTile → HiveMQ MQTT Gateway (Secure TLS Connection)

Reads sensor data from SensorTile USB CDC and publishes to HiveMQ Cloud
over MQTTS (TLS encrypted, port 8883).

DATA FORMAT FROM SENSORTILE:
  Accelerometer: "A,x,y,z\n"           @ 1kHz
  Microphone:    "M,v1,v2,...,v128\n"  @ 125 lines/sec (128 samples each)

MQTT TOPICS:
  switchgear/accel    - JSON: {"x": int, "y": int, "z": int, "t": float}
  switchgear/mic      - JSON: {"samples": [128 ints], "batch": int, "t": float}
  switchgear/status   - Connection status and diagnostics

USAGE:
  1. Fill in your HiveMQ credentials below
  2. Connect SensorTile via USB
  3. Run: python3 main.py
  4. Subscribe on phone app to switchgear/#

Author: SensorTile Condition Monitoring Project
Date: February 2026
"""

import serial
import serial.tools.list_ports
import ssl
import json
import time
import sys
from datetime import datetime

# pip install paho-mqtt
import paho.mqtt.client as mqtt

# ========================== CONFIGURATION ==========================

# HiveMQ Cloud Credentials (fill these in after creating account)
MQTT_BROKER = "7fa53b95ab644109b299a45cabb423a6.s1.eu.hivemq.cloud"  # e.g., "abc123.s1.eu.hivemq.cloud"
MQTT_PORT = 8883                            # TLS port
MQTT_USERNAME = "wipro"
MQTT_PASSWORD = "wiproMQTT1"

# MQTT Topics
TOPIC_ACCEL = "switchgear/accel"
TOPIC_MIC = "switchgear/mic"
TOPIC_STATUS = "switchgear/status"

# Serial port (auto-detect or specify manually)
SERIAL_PORT = "/dev/cu.usbmodemFFFFFFFEFFFF1"  # SensorTile CDC port
SERIAL_BAUD = 115200  # Not used for USB CDC, but required by pyserial

# Publish rate limiting (to avoid overwhelming MQTT)
ACCEL_PUBLISH_INTERVAL = 0.01   # Publish every 10ms (100 Hz max)
MIC_PUBLISH_EVERY_N = 1         # Publish every Nth mic batch (1 = all)

# ========================== MQTT CALLBACKS ==========================

def on_connect(client, userdata, flags, rc, properties=None):
    """Called when connected to MQTT broker."""
    if rc == 0:
        print(f"[MQTT] ✅ Connected to {MQTT_BROKER}")
        # Publish connection status
        status = {
            "status": "online",
            "device": "SensorTile",
            "timestamp": datetime.now().isoformat()
        }
        client.publish(TOPIC_STATUS, json.dumps(status), retain=True)
    else:
        print(f"[MQTT] ❌ Connection failed with code {rc}")
        if rc == 5:
            print("       Check username/password!")

def on_disconnect(client, userdata, rc, properties=None):
    """Called when disconnected from MQTT broker."""
    print(f"[MQTT] Disconnected (rc={rc})")

def on_publish(client, userdata, mid, properties=None):
    """Called when message is published (optional debug)."""
    pass  # Uncomment for debug: print(f"[MQTT] Published mid={mid}")

# ========================== SERIAL PORT DETECTION ==========================

def find_sensortile_port():
    """Auto-detect SensorTile USB CDC port."""
    ports = serial.tools.list_ports.comports()
    
    for port in ports:
        # Look for STM32 CDC device
        if "STM" in port.description.upper() or \
           "CDC" in port.description.upper() or \
           "usbmodem" in port.device.lower():
            print(f"[SERIAL] Found: {port.device} - {port.description}")
            return port.device
    
    # List all available ports
    print("[SERIAL] Available ports:")
    for port in ports:
        print(f"         {port.device}: {port.description}")
    
    return None

# ========================== MAIN GATEWAY ==========================

def main():
    print("=" * 60)
    print("  SensorTile → HiveMQ MQTT Gateway (TLS Secured)")
    print("=" * 60)
    
    # Validate configuration
    if "your-cluster" in MQTT_BROKER or "your-username" in MQTT_USERNAME:
        print("\n❌ ERROR: Please configure HiveMQ credentials!")
        print("   Edit the MQTT_BROKER, MQTT_USERNAME, MQTT_PASSWORD")
        print("   at the top of this file.\n")
        sys.exit(1)
    
    # -------- Setup MQTT Client with TLS --------
    print(f"\n[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT} (TLS)...")
    
    # Use MQTT v5 for better features
    client = mqtt.Client(
        client_id=f"sensortile-gateway-{int(time.time())}",
        protocol=mqtt.MQTTv5
    )
    
    # Set credentials
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    
    # Enable TLS (HiveMQ Cloud uses standard CA certificates)
    client.tls_set(
        ca_certs=None,  # Use system CA store
        certfile=None,
        keyfile=None,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS,
        ciphers=None
    )
    
    # Set callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish = on_publish
    
    # Set Last Will (published if we disconnect unexpectedly)
    will_msg = json.dumps({"status": "offline", "timestamp": datetime.now().isoformat()})
    client.will_set(TOPIC_STATUS, will_msg, retain=True)
    
    # Connect
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[MQTT] ❌ Connection failed: {e}")
        sys.exit(1)
    
    # Start MQTT network loop in background thread
    client.loop_start()
    
    # -------- Setup Serial Port --------
    port = SERIAL_PORT or find_sensortile_port()
    if not port:
        print("\n❌ ERROR: SensorTile not found!")
        print("   Connect SensorTile via USB and try again.\n")
        client.loop_stop()
        sys.exit(1)
    
    print(f"[SERIAL] Opening {port}...")
    try:
        ser = serial.Serial(port, SERIAL_BAUD, timeout=1)
    except Exception as e:
        print(f"[SERIAL] ❌ Failed to open port: {e}")
        client.loop_stop()
        sys.exit(1)
    
    print(f"[SERIAL] ✅ Connected to {port}")
    
    # -------- Main Loop: Read Serial → Publish MQTT --------
    print("\n[GATEWAY] 🚀 Streaming started! Press Ctrl+C to stop.\n")
    
    accel_idx = 0
    mic_batch = 0
    last_accel_publish = 0
    stats = {"accel": 0, "mic": 0, "errors": 0}
    
    try:
        while True:
            line = ser.readline()
            if not line:
                continue
            
            try:
                line = line.decode('utf-8').strip()
            except UnicodeDecodeError:
                stats["errors"] += 1
                continue
            
            if not line:
                continue
            
            parts = line.split(',')
            
            # ---- Accelerometer: A,x,y,z ----
            if parts[0] == 'A' and len(parts) == 4:
                try:
                    x, y, z = int(parts[1]), int(parts[2]), int(parts[3])
                    t = accel_idx / 1000.0  # Time in seconds (1kHz)
                    accel_idx += 1
                    
                    # Rate limit publishing
                    now = time.time()
                    if now - last_accel_publish >= ACCEL_PUBLISH_INTERVAL:
                        payload = json.dumps({
                            "x": x, "y": y, "z": z,
                            "t": round(t, 3),
                            "ts": datetime.now().isoformat()
                        })
                        client.publish(TOPIC_ACCEL, payload, qos=0)
                        last_accel_publish = now
                        stats["accel"] += 1
                        
                except ValueError:
                    stats["errors"] += 1
            
            # ---- Microphone: M,v1,v2,...,v128 ----
            elif parts[0] == 'M' and len(parts) > 1:
                try:
                    samples = [int(v) for v in parts[1:]]
                    t = (mic_batch * 128) / 16000.0  # Time in seconds (16kHz)
                    
                    # Publish every Nth batch
                    if mic_batch % MIC_PUBLISH_EVERY_N == 0:
                        payload = json.dumps({
                            "samples": samples,
                            "batch": mic_batch,
                            "t": round(t, 4),
                            "ts": datetime.now().isoformat()
                        })
                        client.publish(TOPIC_MIC, payload, qos=0)
                        stats["mic"] += 1
                    
                    mic_batch += 1
                    
                except ValueError:
                    stats["errors"] += 1
            
            # ---- Stats every 5 seconds ----
            if (stats["accel"] + stats["mic"]) % 500 == 0 and stats["accel"] > 0:
                print(f"[STATS] Accel: {stats['accel']} | Mic: {stats['mic']} | Errors: {stats['errors']}")
    
    except KeyboardInterrupt:
        print("\n\n[GATEWAY] Shutting down...")
    
    finally:
        # Cleanup
        status = json.dumps({"status": "offline", "timestamp": datetime.now().isoformat()})
        client.publish(TOPIC_STATUS, status, retain=True)
        time.sleep(0.5)  # Let message send
        
        ser.close()
        client.loop_stop()
        client.disconnect()
        
        print(f"[STATS] Final - Accel: {stats['accel']} | Mic: {stats['mic']} | Errors: {stats['errors']}")
        print("[GATEWAY] Goodbye! 👋")

# ========================== ENTRY POINT ==========================

if __name__ == "__main__":
    main()
