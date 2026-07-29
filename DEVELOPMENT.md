# 🛠️ ARUGA Developer & Customization Guide

Welcome to the **ARUGA Developer Guide**! This document explains how the ARUGA backend, database, predictive model, and hardware interfaces work, and provides step-by-step instructions on how to modify and extend the system for your own research or custom deployment.

---

## 📑 Table of Contents
1. [Architecture & Data Flow](#1-architecture--data-flow)
2. [How to Modify Vital Signs Thresholds & Age Groups](#2-how-to-modify-vital-signs-thresholds--age-groups)
3. [How the API & Hardware Interfaces Work](#3-how-the-api--hardware-interfaces-work)
4. [How to Modify the Predictive Analytics Model](#4-how-to-modify-the-predictive-analytics-model)
5. [How to Customize the Dashboard UI & Charts](#5-how-to-customize-the-dashboard-ui--charts)
6. [How to Add New Fields to Database Models](#6-how-to-add-new-fields-to-database-models)
7. [Connecting Physical ESP32 Hardware (C++ Code Example)](#7-connecting-physical-esp32-hardware-c-code-example)

---

## 1. Architecture & Data Flow

ARUGA is designed around a modular decoupled architecture:

```
[ ESP32 Wearable Sensors ] ---> HTTP POST /api/server/vitals-hr/{id} ---> [ vitals_service.py ]
                                                                                   |
[ ESP32-CAM Module ]       ---> WS /ws/server/image/{id}                ---> [ SQLAlchemy DB ]
                                                                                   |
[ Remote Caregiver Browser] <--- WS /ws/live-feed & REST APIs           <--- [ FastAPI Routers ]
```

- **[app/config.py](app/config.py)**: Centralizes environment variables (`ARUGA_API_KEY`, `SECRET_KEY`) loaded from `.env`.
- **[app/models.py](app/models.py)**: SQLAlchemy ORM models (`User`, `VitalRecord`, `Medicine`, `Notification`, `LiveFeedImage`) with indexing for fast lookups.
- **[app/services/vitals_service.py](app/services/vitals_service.py)**: Evaluates physiological data against clinical parameters in `app/parameter.json`.
- **[app/services/prediction_service.py](app/services/prediction_service.py)**: Executes ARIMA time-series forecasting.
- **[app/routers/](app/routers/)**: FastAPI route handlers grouped by domain (`auth.py`, `vitals.py`, `esp32.py`, `live_feed.py`, `dashboard.py`).

---

## 2. How to Modify Vital Signs Thresholds & Age Groups

All clinical threshold rules are defined in human-readable JSON inside **[app/parameter.json](app/parameter.json)**.


### Editing Parameter Thresholds
Open `app/parameter.json`. Each block defines normal, at-risk, and critical boundaries for an age category:

```json
{
  "id": "young_middle_adult",
  "age_group": "Young/Middle Adult",
  "age_range": { "unit": "years", "min": 19, "max": 64 },
  "heart_rate_bpm": {
    "critical_low": { "operator": "<", "value": 50 },
    "at_risk_low": { "min": 50, "max": 59 },
    "normal": { "min": 60, "max": 100 },
    "at_risk_high": { "min": 101, "max": 120 },
    "critical_high": { "operator": ">", "value": 120 }
  }
}
```

- **To adjust numerical limits**: Change `value`, `min`, or `max` numbers.
- **To add a new age group**: Add a new dictionary object to the `"vital_thresholds"` array in `app/parameter.json`.

> **Note**: The alert engine in `app/services/vitals_service.py` automatically picks up changes to `app/parameter.json` without requiring changes to Python code!

---

## 3. How the API & Hardware Interfaces Work

### A. ESP32 Vitals Submission (`POST /api/server/vitals-hr/{patient_id}`)
- **Authentication**: Requires header `x-api-key: <YOUR_API_KEY>` matching `ARUGA_API_KEY` in `.env`.
- **Payload Format (JSON)**:
  ```json
  {
    "spo2": 98,
    "heartrate": 72,
    "temp": 36.5,
    "bp-systolic": 120,
    "bp-diastolic": 80,
    "error": false
  }
  ```
- **Sensor Error Handling**: If `"error": true` is passed (e.g. sensor dislodged or no finger detected), the system flags `sensor_error=True` and changes the status LED to `"error"`. `0` values for individual vitals are treated as unread (`NULL`).

### B. ESP32 Display Query & LCD Lines (`GET /api/esp32/alerts/{patient_id}`)
Used by physical LCD screens on the companion robot. Returns structured line content:
```json
{
  "led": "green",
  "lcd1": "HR: 72 | SpO2: 98%",
  "lcd2": "Temp: 36.5C",
  "lcd3": "BP: 120/80",
  "lcd4": "2026-07-28 22:00:00",
  "alert": false,
  "smsalert": false,
  "medicinedispense": 0
}
```

### C. Live Camera Feed WebSocket (`/ws/server/image/{patient_id}`)
1. ESP32-CAM opens WebSocket connection to `/ws/server/image/1`.
2. First text message sent: `x-api-key: YOUR_ARUGA_API_KEY`.
3. Subsequent binary messages: Raw JPEG frame bytes (`b"\xff\xd8\xff..."`).
4. Server saves frames to `static/uploads/live_feed/1/` and broadcasts metadata to dashboard viewers over `/ws/live-feed`.

### D. Debug Overrides (`POST /api/debug/override/{patient_id}`)
Allows testing emergency alerts without hardware sensors:
```json
{
  "smsalert": true,
  "smsalertmsg": "Simulated Fall Emergency",
  "medicinedispense": 1,
  "led": "red",
  "alert": true
}
```

---

## 4. How to Modify the Predictive Analytics Model

ARUGA uses ARIMA forecasting in **[app/prediction_model.py](app/prediction_model.py)**.

### Changing ARIMA Orders or Prediction Steps
Open `app/prediction_model.py`:
```python
orders_by_vital = {
    "spo2":   [(1, 0, 1), (1, 0, 0)], # (p, d, q) orders
    "hr":     [(1, 1, 0), (2, 1, 2), (1, 0, 1)],
    "temp":   [(1, 0, 0), (1, 1, 0)],
    "sys_bp": [(1, 1, 0), (1, 0, 1)],
    "dia_bp": [(1, 1, 0), (1, 0, 1)],
}
```
- **To change forecasting order**: Modify the list of `(p, d, q)` tuples for each vital.
- **To change forecasting horizon**: Pass a different `steps` integer (default: 20 data points) to `predict_vitals(..., steps=30)`.
- **Polynomial Fallback**: If ARIMA fails to converge on noisy data, `_poly_fallback()` is executed automatically to ensure continuous chart rendering.

---

## 5. How to Customize the Dashboard UI & Charts

### Styling & Color Scheme
Theme variables are stored in **[static/css/style.css](static/css/style.css)**:
```css
:root {
    --pink-500: #f4a4b5; /* Primary accent color */
    --pink-700: #c87886;
    --gray-800: #1f2937;
    /* ... */
}
```
Edit these CSS custom properties to change the color palette across the entire application.

### Adding a New Dashboard Tab
1. Open **[templates/dashboard.html](templates/dashboard.html)**:
   Add a new button inside `.sidebar`:
   ```html
   <button class="tab-btn" data-tab="custom-tab">
       <i class="fa-solid fa-gear"></i> Custom Tab
   </button>
   ```
   Add a corresponding panel inside `.dashboard-content`:
   ```html
   <div class="tab-panel" id="tab-custom-tab">
       <div class="card"><h3>Custom Tab Content</h3></div>
   </div>
   ```
2. Open **[static/js/dashboard.js](static/js/dashboard.js)**:
   Add your tab name to `validTabs` in `restoreTabFromHash()` so URL hash routing works (e.g. `#custom-tab`).

---

## 6. How to Add New Fields to Database Models

Suppose you want to add a `respiratory_rate` field to vital records:

1. **Update ORM Model** in **[app/models.py](app/models.py)**:
   ```python
   class VitalRecord(Base):
       # ...
       respiratory_rate = Column(Integer, nullable=True)
   ```
2. **Update Request Schema** in **[app/schemas.py](app/schemas.py)**:
   ```python
   class VitalsUploadPayload(BaseModel):
       respiratory_rate: Optional[int] = None
   ```
3. **Update Vitals Ingestion** in **[app/routers/esp32.py](app/routers/esp32.py)**:
   Extract `respiratory_rate` from incoming JSON payload and save it in `VitalRecord(...)`.


---

## 7. Connecting Physical ESP32 Hardware (C++ Code Example)

Below is an example Arduino / C++ snippet for sending vitals telemetry from an ESP32 to ARUGA:

```cpp
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* serverUrl = "http://YOUR_SERVER_IP:8000/api/server/vitals-hr/1";
const char* apiKey = "YOUR_ARUGA_API_KEY";

void sendVitals(int hr, int spo2, float temp, int sys, int dia) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("x-api-key", apiKey);

    StaticJsonDocument<200> doc;
    doc["spo2"] = spo2;
    doc["heartrate"] = hr;
    doc["temp"] = temp;
    doc["bp-systolic"] = sys;
    doc["bp-diastolic"] = dia;
    doc["error"] = false;

    String requestBody;
    serializeJson(doc, requestBody);

    int httpResponseCode = http.POST(requestBody);
    Serial.printf("HTTP Response code: %d\n", httpResponseCode);
    http.end();
  }
}
```

---

## 💬 Support & Questions

For questions or feedback regarding customizing ARUGA, please open an issue in the GitHub repository or contact the STEM Research Team at Muntinlupa National High School.
