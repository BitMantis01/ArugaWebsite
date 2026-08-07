import hmac
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import API_KEY, ENABLE_DEBUG_ENDPOINTS
from app.database import get_db
from app.models import User, VitalRecord, Notification, Medicine

from app.schemas import VitalsUploadPayload, DebugOverridePayload
from app.services.vitals_service import check_vitals_alert

router = APIRouter(tags=["esp32"])

# In-memory debug overrides dictionary
_debug_overrides: Dict[int, dict] = {}

DEFAULT_DEBUG_OVERRIDE = {
    "smsalert": False,
    "smsalertmsg": "none",
    "medicinedispense": 0,
    "move": False,
    "led": "",        # empty = use real
    "lcd3": "",       # empty = use real
    "alert": None,    # None = use real, True/False = override
}


def verify_api_key(request: Request):
    """Verify x-api-key header using constant-time comparison. Raises 401 if missing or invalid."""
    key = request.headers.get("x-api-key")
    if not key or not hmac.compare_digest(key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def verify_debug_enabled():
    """Ensure debug override endpoints are enabled in configuration."""
    if not ENABLE_DEBUG_ENDPOINTS:
        raise HTTPException(status_code=403, detail="Debug endpoints are disabled in production environment")


@router.post("/api/server/vitals-hr/{patient_id}")
async def api_upload_vitals(
    patient_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    verify_api_key(request)

    user = db.query(User).filter(User.id == patient_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    spo2_raw = body.get("spo2")
    heartrate_raw = body.get("heartrate")
    temp_raw = body.get("temp")
    bp_systolic_raw = body.get("bp-systolic")
    bp_diastolic_raw = body.get("bp-diastolic")
    sensor_error = body.get("error", False)

    spo2 = spo2_raw if (spo2_raw is not None and spo2_raw != 0) else None
    heartrate = heartrate_raw if (heartrate_raw is not None and heartrate_raw != 0) else None
    temp = temp_raw if (temp_raw is not None and temp_raw != 0) else None
    bp_systolic = bp_systolic_raw if (bp_systolic_raw is not None and bp_systolic_raw != 0) else None
    bp_diastolic = bp_diastolic_raw if (bp_diastolic_raw is not None and bp_diastolic_raw != 0) else None

    vital = VitalRecord(
        user_id=patient_id,
        spo2=float(spo2) if spo2 is not None else None,
        heart_rate=int(heartrate) if heartrate is not None else None,
        temperature=float(temp) if temp is not None else None,
        systolic_bp=int(bp_systolic) if bp_systolic is not None else None,
        diastolic_bp=int(bp_diastolic) if bp_diastolic is not None else None,
        sensor_error=bool(sensor_error),
        recorded_at=datetime.utcnow(),
    )
    db.add(vital)
    db.commit()
    db.refresh(vital)

    led, is_alert, alert_reasons = check_vitals_alert(
        user.age,
        int(heartrate) if heartrate is not None else None,
        float(spo2) if spo2 is not None else None,
        float(temp) if temp is not None else None,
        int(bp_systolic) if bp_systolic is not None else None,
        int(bp_diastolic) if bp_diastolic is not None else None,
        sensor_error=bool(sensor_error),
    )

    if is_alert and alert_reasons:
        alert_msg = " | ".join(alert_reasons)
        notif_level = "critical" if led in ("red", "error") else "warning"
        db.add(Notification(
            user_id=patient_id,
            title="Vitals Alert",
            message=f"({led.upper()}) Out of normal range: {alert_msg}",
            level=notif_level,
            created_at=datetime.utcnow(),
        ))
        db.commit()

    return JSONResponse({
        "id": vital.id,
        "patient_id": patient_id,
        "spo2": vital.spo2,
        "heart_rate": vital.heart_rate,
        "temperature": vital.temperature,
        "systolic_bp": vital.systolic_bp,
        "diastolic_bp": vital.diastolic_bp,
        "recorded_at": vital.recorded_at.isoformat(),
    }, status_code=201)


@router.get("/api/esp32/alerts/{patient_id}")
async def api_esp32_alerts(
    patient_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    verify_api_key(request)

    user = db.query(User).filter(User.id == patient_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    # Query latest overall record for sensor_error status
    latest = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == patient_id)
        .order_by(VitalRecord.recorded_at.desc())
        .first()
    )

    # Query newest known valid data record (error-free with readings)
    latest_valid = (
        db.query(VitalRecord)
        .filter(
            VitalRecord.user_id == patient_id,
            VitalRecord.sensor_error == False,
            (VitalRecord.heart_rate.isnot(None)) | (VitalRecord.spo2.isnot(None)) | (VitalRecord.temperature.isnot(None))
        )
        .order_by(VitalRecord.recorded_at.desc())
        .first()
    )

    # Use newest valid record if available; otherwise fall back to latest overall
    target_rec = latest_valid or latest

    if target_rec:
        hr = target_rec.heart_rate
        spo2_val = target_rec.spo2
        temp_val = target_rec.temperature
        sys_bp = target_rec.systolic_bp
        dia_bp = target_rec.diastolic_bp
        rec_time = target_rec.recorded_at
    else:
        hr = spo2_val = temp_val = sys_bp = dia_bp = None
        rec_time = datetime.utcnow()

    sensor_error = latest.sensor_error if latest else False

    # If BP is missing from target_rec, fetch newest known valid BP reading
    if sys_bp is None or dia_bp is None:
        bp_rec = (
            db.query(VitalRecord)
            .filter(
                VitalRecord.user_id == patient_id,
                VitalRecord.sensor_error == False,
                VitalRecord.systolic_bp.isnot(None)
            )
            .order_by(VitalRecord.recorded_at.desc())
            .first()
        )
        if bp_rec:
            sys_bp = bp_rec.systolic_bp
            dia_bp = bp_rec.diastolic_bp

    # Format LCD lines showing newest known data
    lcd1_parts = []
    if hr is not None:
        lcd1_parts.append(f"HR: {int(hr)}")
    if spo2_val is not None:
        lcd1_parts.append(f"SpO2: {int(spo2_val)}%")
    lcd1 = " | ".join(lcd1_parts) if lcd1_parts else ""

    lcd2_parts = []
    if temp_val is not None:
        lcd2_parts.append(f"Temp: {float(temp_val):.1f}C")
    lcd2 = " | ".join(lcd2_parts) if lcd2_parts else ""

    if sys_bp is not None and dia_bp is not None:
        lcd3 = f"BP: {int(sys_bp)}/{int(dia_bp)}"
    elif sys_bp is not None:
        lcd3 = f"BP: {int(sys_bp)}/-"
    else:
        lcd3 = "BP: --/--"


    # Line 4: GMT+8 recorded timestamp of the newest known data displayed
    lcd4_time = (rec_time + timedelta(hours=8)) if rec_time else (datetime.utcnow() + timedelta(hours=8))
    lcd4 = lcd4_time.strftime("%Y-%m-%d %H:%M:%S")


    led, is_alert, alert_reasons = check_vitals_alert(
        user.age, hr, spo2_val, temp_val, sys_bp, dia_bp, sensor_error=sensor_error
    )

    # Compute active medicine slot due (1 to 7) in GMT+8 (newest due slot first)
    now_gmt8 = datetime.utcnow() + timedelta(hours=8)
    auto_meddispense = 0

    due_med = (
        db.query(Medicine)
        .filter(
            Medicine.user_id == patient_id,
            Medicine.active == True,
            Medicine.is_dispensed == False,
            Medicine.scheduled_datetime.isnot(None),
            Medicine.scheduled_datetime <= now_gmt8,
        )
        .order_by(Medicine.scheduled_datetime.desc(), Medicine.slot_number.desc())
        .first()
    )

    if due_med:
        auto_meddispense = due_med.slot_number


    overrides = _debug_overrides.get(patient_id, {})
    final_smsalert = overrides.get("smsalert", False)
    final_smsalertmsg = overrides.get("smsalertmsg", "none")
    override_med = overrides.get("medicinedispense")
    final_meddispense = override_med if (override_med is not None and override_med > 0) else auto_meddispense

    if overrides.get("led"):
        led = overrides["led"]
    if overrides.get("lcd3"):
        lcd3 = overrides["lcd3"]
    if overrides.get("alert") is not None:
        is_alert = overrides["alert"]

    final_move = overrides.get("move", False)


    return JSONResponse({
        "led": led,
        "lcd1": lcd1,
        "lcd2": lcd2,
        "lcd3": lcd3,
        "lcd4": lcd4,
        "alert": is_alert,
        "smsalert": final_smsalert,
        "smsalertmsg": final_smsalertmsg,
        "medicinedispense": final_meddispense,
        "move": final_move,
        "timestamp": now_gmt8.isoformat(),

        "spo2": spo2_val,
        "heartrate": hr,
        "temp": temp_val,
        "bp-systolic": sys_bp,
        "bp-diastolic": dia_bp,
        "sensor_error": sensor_error,
    })


@router.get("/api/debug/override/{patient_id}")
def api_get_debug_override(patient_id: int, request: Request):
    verify_api_key(request)
    verify_debug_enabled()
    return JSONResponse(_debug_overrides.get(patient_id, dict(DEFAULT_DEBUG_OVERRIDE)))


@router.post("/api/debug/override/{patient_id}")
async def api_set_debug_override(
    patient_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    verify_api_key(request)
    verify_debug_enabled()

    user = db.query(User).filter(User.id == patient_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    current = _debug_overrides.get(patient_id, dict(DEFAULT_DEBUG_OVERRIDE))
    for field in DEFAULT_DEBUG_OVERRIDE:
        if field in body:
            current[field] = body[field]

    _debug_overrides[patient_id] = current
    return JSONResponse({"status": "ok", "overrides": current})


@router.delete("/api/debug/override/{patient_id}")
def api_clear_debug_override(patient_id: int, request: Request):
    verify_api_key(request)
    verify_debug_enabled()
    _debug_overrides.pop(patient_id, None)
    return JSONResponse({"status": "cleared"})

