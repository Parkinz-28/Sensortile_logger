#!/usr/bin/env python3
"""
SensorTile Serial Logger with CSV Export and Email Alerts

Auto-detects data format:
  - RAW mode:     x,y,z,m1,m2,...,m16  (STREAM_RAW=1)
  - REDUCED mode: x,y,z,peak,avg       (STREAM_RAW=0)

Usage:
    python3 main.py

Requirements:
    pip install pyserial
"""

import serial
import serial.tools.list_ports
import csv
import smtplib
import time
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from threading import Thread, Event

# ========================== CONFIGURATION ==========================

# Serial port (None = auto-detect)
SERIAL_PORT = "/dev/cu.usbmodemFFFFFFFEFFFF1"

# CSV file settings
CSV_FILENAME = "sensor_data_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".csv"

# Email configuration
EMAIL_ENABLED = True  # Set True to enable
EMAIL_INTERVAL_MINUTES = 1
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "rainarouban@gmail.com"
SENDER_PASSWORD = "zurw xmnc erjn gtpn"  # Use Gmail App Password
RECIPIENT_EMAILS = ["rouban.01@wipro.com","parkinzyt@gmail.com"]

# ===================================================================

class SensorLogger:
    def __init__(self):
        self.csv_file = None
        self.csv_writer = None
        self.serial_port = None
        self.running = False
        self.stop_event = Event()
        self.sample_count = 0
        self.mode = None  # 'raw' or 'reduced'
        self.csv_initialized = False
        
    def find_sensortile(self):
        """Auto-detect SensorTile USB port."""
        ports = serial.tools.list_ports.comports()
        for port in ports:
            desc = port.description.upper()
            if "STM" in desc or "CDC" in desc or "usbmodem" in port.device.lower():
                return port.device
        return None
    
    def init_csv(self, mode):
        """Initialize CSV file with headers based on mode."""
        if self.csv_initialized:
            return
            
        self.csv_file = open(CSV_FILENAME, 'w', newline='')
        self.csv_writer = csv.writer(self.csv_file)
        
        if mode == 'raw':
            # x,y,z + 16 mic samples + timestamp
            headers = ["x", "y", "z"] + [f"m{i+1}" for i in range(16)] + ["timestamp"]
        else:
            # x,y,z,peak,avg + timestamp
            headers = ["x", "y", "z", "mic_peak", "mic_avg", "timestamp"]
        
        self.csv_writer.writerow(headers)
        self.csv_file.flush()
        self.csv_initialized = True
        print(f"[CSV] Headers: {headers}")
    
    def write_sample(self, row):
        """Write a sample to CSV."""
        self.csv_writer.writerow(row)
        self.sample_count += 1
        if self.sample_count % 500 == 0:
            self.csv_file.flush()
            print(f"[LOG] {self.sample_count} samples")
    
    def send_email(self):
        """Send CSV file via email to all recipients."""
        if not EMAIL_ENABLED or not RECIPIENT_EMAILS:
            return
        
        try:
            msg = MIMEMultipart()
            msg['From'] = SENDER_EMAIL
            msg['To'] = ", ".join(RECIPIENT_EMAILS)
            msg['Subject'] = f"SensorTile Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            body = f"""SensorTile Data Report
            
Generated: {datetime.now().isoformat()}
Mode: {self.mode.upper()}
Samples: {self.sample_count}
File: {CSV_FILENAME}
"""
            msg.attach(MIMEText(body, 'plain'))
            
            # Attach CSV
            if os.path.exists(CSV_FILENAME):
                with open(CSV_FILENAME, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', 
                                    f'attachment; filename="{CSV_FILENAME}"')
                    msg.attach(part)
            
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
            server.quit()
            print(f"[EMAIL] Sent to {len(RECIPIENT_EMAILS)} recipient(s)")
            
        except Exception as e:
            print(f"[EMAIL] Failed: {e}")
    
    def email_scheduler(self):
        """Background thread for periodic emails."""
        interval = EMAIL_INTERVAL_MINUTES * 60
        while not self.stop_event.wait(interval):
            if self.running:
                self.send_email()
    
    def process_line(self, line):
        """Parse serial line and log to CSV."""
        # Skip debug messages
        if line.startswith('#'):
            print(f"[DEBUG] {line}")
            return
        
        parts = line.split(',')
        if len(parts) < 5:
            return
        
        try:
            # Parse accel
            x, y, z = int(parts[0]), int(parts[1]), int(parts[2])
            mic_parts = parts[3:]
            timestamp = datetime.now().isoformat()
            
            # Detect mode from mic data count
            if len(mic_parts) == 2:
                # REDUCED mode: peak, avg
                if self.mode != 'reduced':
                    self.mode = 'reduced'
                    self.init_csv('reduced')
                    print("[MODE] Detected REDUCED (peak, avg)")
                
                peak, avg = int(mic_parts[0]), int(mic_parts[1])
                self.write_sample([x, y, z, peak, avg, timestamp])
                
            elif len(mic_parts) >= 8:
                # RAW mode: m1,m2,...,m16
                if self.mode != 'raw':
                    self.mode = 'raw'
                    self.init_csv('raw')
                    print(f"[MODE] Detected RAW ({len(mic_parts)} samples)")
                
                mic_samples = [int(m) for m in mic_parts[:16]]
                # Pad if less than 16
                while len(mic_samples) < 16:
                    mic_samples.append(0)
                self.write_sample([x, y, z] + mic_samples + [timestamp])
                
        except ValueError:
            pass
    
    def run(self):
        """Main loop."""
        port = SERIAL_PORT or self.find_sensortile()
        if not port:
            print("[ERROR] SensorTile not found")
            return
        
        print(f"[START] Port: {port}")
        print(f"[START] CSV: {CSV_FILENAME}")
        print(f"[START] Email: {'Every ' + str(EMAIL_INTERVAL_MINUTES) + ' min' if EMAIL_ENABLED else 'Disabled'}")
        print("[START] Waiting for data to detect mode...")
        
        self.serial_port = serial.Serial(port, 115200, timeout=1)
        self.running = True
        
        # Start email scheduler
        if EMAIL_ENABLED:
            Thread(target=self.email_scheduler, daemon=True).start()
        
        # Main loop
        try:
            while True:
                line = self.serial_port.readline()
                if not line:
                    continue
                try:
                    text = line.decode('utf-8').strip()
                    if text:
                        self.process_line(text)
                except UnicodeDecodeError:
                    pass
                    
        except KeyboardInterrupt:
            print("\n[STOP] Shutting down...")
        finally:
            self.running = False
            self.stop_event.set()
            if self.serial_port:
                self.serial_port.close()
            if self.csv_file:
                self.csv_file.close()
            print(f"[DONE] {self.sample_count} samples saved to {CSV_FILENAME}")

# ========================== ENTRY POINT ==========================

if __name__ == "__main__":
    SensorLogger().run()
