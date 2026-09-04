"""
Test script: Populate vitals data by sending random values to the API.
Run: python test_populate_vitals.py
Press Ctrl+C to stop.
"""
import json
import urllib.request
import random
import time
from app.config import API_KEY


API_URL = "https://aruga.bitmantis.xyz/api/server/vitals-hr/5"


SPO2_MEAN = 97
HR_MEAN = 75
TEMP_MEAN = 36.6
SYS_MEAN = 118
DIA_MEAN = 78

patient_id = API_URL.rstrip("/").split("/")[-1]
print(f"Populating vitals for patient {patient_id} (Ctrl+C to stop)...")
count = 0

while True:
    spo2 = max(85, min(100, int(random.gauss(SPO2_MEAN, 1.5))))
    hr = max(50, min(130, int(random.gauss(HR_MEAN, 8))))
    temp = round(max(35.0, min(38.0, random.gauss(TEMP_MEAN, 0.3))), 1)
    sys_bp = max(90, min(160, int(random.gauss(SYS_MEAN, 8))))
    dia_bp = max(55, min(100, int(random.gauss(DIA_MEAN, 6))))

    # Occasionally spike vitals to test alerts (5% chance)
    if random.random() < 0.05:
        spo2 = random.randint(82, 89)
        sys_bp = random.randint(150, 170)

    payload = json.dumps({
        "spo2": spo2,
        "heartrate": hr,
        "temp": temp,
        "bp-systolic": sys_bp,
        "bp-diastolic": dia_bp,
    }).encode()

    req = urllib.request.Request(API_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", API_KEY)
    req.add_header("User-Agent", "ARUGA-Hardware-Client/1.0 (ESP32-Simulator)")

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            count += 1
            print(f"[{count:04d}] {resp.status} | SpO2:{spo2}%  HR:{hr}  Temp:{temp}  BP:{sys_bp}/{dia_bp}")
    except urllib.error.HTTPError as e:
        count += 1
        print(f"[{count:04d}] {e.code} | {e.read().decode()}")
    except Exception as e:
        count += 1
        print(f"[{count:04d}] ERR | {e}")

    time.sleep(1)
