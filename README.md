# 🩺 Project ARUGA — Research Dashboard & Health Analytics Platform

An intelligent preventive healthcare ecosystem combining IoT-based companion robotics, real-time physiological telemetry, **ARIMA time-series forecasting**, live camera streaming, and automated medication dispensing.

---

## 📌 Overview

**ARUGA** (*Development of an Intelligent Preventive Healthcare System with Smart Medication Dispensing, Continuous Vital Sign Monitoring, and Early Health Warning*) is a research initiative developed at **Muntinlupa National High School (STEM Strand)**.

As the population of older adults living independently grows, managing chronic conditions and identifying early physiological shifts before emergencies occur remains a critical challenge. ARUGA bridges this gap by integrating non-invasive wearable sensors, hardware actuators, and machine learning time-series analytics into a single responsive web platform.

---

## ✨ Key Features

- **📶 Real-Time Vital Signs Telemetry**: Continuous tracking of Blood Oxygen Saturation ($\text{SpO}_2$), Heart Rate (BPM), Body Temperature (°C), and Blood Pressure ($\text{SYS}/\text{DIA}$).
- **📈 ARIMA Predictive Analytics**: Autoregressive Integrated Moving Average modeling on 100 historical data points to predict vital sign trends 20 steps into the future, backed by residual bootstrapping and polynomial regression fallbacks.
- **🟢 Age-Stratified Risk Assessment**: Dynamic evaluation against clinical threshold parameters ([app/parameter.json](app/parameter.json)) categorizing health status into **Green** (Normal), **Yellow** (At Risk), or **Red** (Critical).

- **📹 Live Camera Feed Streaming**: Low-latency binary JPEG snapshot ingestion from ESP32-CAM devices over WebSockets with automatic dashboard broadcasting.
- **💊 Smart Automated Medication Dispenser**: Dispensing schedules integrated with servo motor actuation triggers and real-time clock (RTC) synchronization.
- **📟 ESP32 LCD & LED Device Sync**: Dual-line LCD status payload generation and LED color indicator synchronization for physical companion hardware.

---

## 🛠️ Technology Stack

### Backend & API
- **Language**: Python 3.10+
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) & Starlette
- **ORM & Database**: SQLAlchemy 2.0 with SQLite / PostgreSQL support
- **Real-Time Communication**: WebSockets (`websockets`, `uvicorn`)

### Data Science & Predictive Analytics
- **Forecasting**: `statsmodels` (ARIMA), `scikit-learn`, `pandas`, `numpy`

### Frontend & UI
- **Styling**: Modern Vanilla CSS3 (Glassmorphism design system, responsive CSS variables)
- **Visualization**: [Chart.js 4.x](https://www.chartjs.org/) with multi-stop gradient rendering
- **Templating**: Jinja2 HTML5 templates

### Hardware / IoT Integration
- **Microcontrollers**: ESP32, ESP32-CAM
- **Sensors**: MAX30102 / Pulse Oximeter, DS18B20 Temperature Sensor
- **Actuators & Accessories**: Servo Motors, RTC Module, LCD Screen, SIM800L GSM Module

---

## 📁 Repository Structure

```
ArugaWebsite/
├── app/                      # <--- ALL Application Code & Package Modules
│   ├── __init__.py
│   ├── main.py               # Application entry point & router registration
│   ├── config.py             # Environment configuration loader (.env)
│   ├── database.py           # SQLAlchemy engine & session setup
│   ├── models.py             # Database models (User, VitalRecord, Medicine, etc.)
│   ├── schemas.py            # Pydantic validation schemas
│   ├── parameter.json        # Clinical age-based vital threshold specs
│   ├── prediction_model.py   # ARIMA & polynomial math logic
│   ├── routers/              # FastAPI modular APIRouters
│   │   ├── auth.py           # User authentication & session management
│   │   ├── dashboard.py      # HTML page rendering routes
│   │   ├── esp32.py          # ESP32 hardware endpoints & debug overrides
│   │   ├── live_feed.py      # Camera WebSocket streaming & broadcasting
│   │   └── vitals.py         # Vitals history, latest, & prediction routes
│   └── services/             # Business logic services
│       ├── vitals_service.py # Threshold evaluation & alert generation
│       └── prediction_service.py # Forecasting wrapper service
├── main.py                   # Root entry point delegating to app.main:app
├── test_populate_vitals.py   # Telemetry simulation script
├── .env.example              # Environment template file
├── requirements.txt          # Dependencies list
├── static/                   # Static assets (CSS, JS, images, uploads)
└── templates/                # Jinja2 HTML templates
```

---

## 🚀 Quick Start & Installation

### 1. Prerequisites
- Python **3.10** or higher
- Git

### 2. Clone the Repository
```bash
git clone https://github.com/your-username/ArugaWebsite.git
cd ArugaWebsite
```

### 3. Create a Virtual Environment & Install Dependencies
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and set your API key:
```bash
cp .env.example .env
```
Edit `.env`:
```env
ENVIRONMENT=development
ARUGA_API_KEY=aruga-dev-key-change-in-production
SECRET_KEY=aruga-secret-key-change-in-production-2026
ENABLE_DEBUG_ENDPOINTS=true
ENABLE_API_DOCS=true
```

### 5. Run the Server
```bash
python main.py
# or
uvicorn main.py:app --reload --host 0.0.0.0 --port 8000
```
Open your browser and navigate to **`http://localhost:8000`**.

---

## 🔒 Security & Data Protection

ARUGA is designed with robust security measures to protect Protected Health Information (PHI):
- **Password Security**: Bcrypt auto-salted hashing with server-side length enforcement (minimum 8 characters).
- **Session Protection**: `SameSite=lax` cookie policy, 24-hour expiration, `https_only` in production mode, and POST-only logout.
- **WebSocket Authorization**: Live feed streams require authenticated patient session cookies.
- **Constant-Time Verification**: Hardware API key validation uses `hmac.compare_digest` to prevent timing attacks.
- **Hardened HTTP Headers**: Automatic `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, and `HSTS` header injection.

---

## 🧪 Simulation & Testing

To test telemetry ingestion and alert generation without physical hardware, run the simulation script:
```bash
python test_populate_vitals.py
```
This script generates synthetic vital sign streams for Patient ID `1` every 5 seconds and submits them to the backend.

---

## 🛰️ API Reference Overview

| Protocol | Method | Endpoint | Description |
| :--- | :--- | :--- | :--- |
| **HTTP** | `POST` | `/api/signup` | Register a new user account (min 8 char password) |
| **HTTP** | `POST` | `/api/login` | Authenticate user and initiate session |
| **HTTP** | `POST` | `/api/logout` | Terminate active user session |
| **HTTP** | `GET` | `/api/vitals/latest` | Fetch most recent vital sign record |
| **HTTP** | `GET` | `/api/vitals/history` | Query historical vitals telemetry |
| **HTTP** | `GET` | `/api/predictions` | Calculate 20-step ARIMA vitals forecast |
| **HTTP** | `POST` | `/api/server/vitals-hr/{patient_id}` | ESP32 vital signs submission (x-api-key required) |
| **HTTP** | `GET` | `/api/esp32/alerts/{patient_id}` | ESP32 display payload & alert query (x-api-key required) |
| **WS** | `WS` | `/ws/server/image/{patient_id}` | ESP32-CAM JPEG binary frame stream |
| **WS** | `WS` | `/ws/live-feed` | Dashboard real-time live feed subscription (session authenticated) |


---

## 🛠️ Developer & Customization Guide

Looking to modify clinical thresholds, connect custom ESP32 sensors, tweak ARIMA prediction orders, or add new database fields? Check out our comprehensive **[Developer & Customization Guide (DEVELOPMENT.md)](DEVELOPMENT.md)**.

---

## 📜 License & Citation

Developed for academic research at **Muntinlupa National High School (STEM Strand)**.  
Distributed under the **MIT License**. See `LICENSE` for details.

