from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import API_KEY
from app.database import get_db
from app.models import User, VitalRecord, Notification
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
    """Verify x-api-key header. Raises 401 if missing or invalid."""
    key = request.headers.get("x-api-key")
    if not key or key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


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

    latest = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == patient_id)
        .order_by(VitalRecord.recorded_at.desc())
        .first()
    )

    latest_notif = (
        db.query(Notification)
        .filter(Notification.user_id == patient_id, Notification.level.in_(["critical", "warning"]))
        .order_by(Notification.created_at.desc())
        .first()
    )

    now = datetime.utcnow()

    if latest:
        hr = latest.heart_rate
        spo2_val = latest.spo2
        temp_val = latest.temperature
        sys_bp = latest.systolic_bp
        dia_bp = latest.diastolic_bp
        sensor_error = latest.sensor_error
    else:
        hr = spo2_val = temp_val = sys_bp = dia_bp = None
        sensor_error = False

    lcd_hr, lcd_spo2, lcd_temp, lcd_sys, lcd_dia = hr, spo2_val, temp_val, sys_bp, dia_bp
    last_good = None

    if sensor_error and (hr is None and spo2_val is None):
        last_good = (
            db.query(VitalRecord)
            .filter(
                VitalRecord.user_id == patient_id,
                VitalRecord.sensor_error == False,
                VitalRecord.heart_rate.isnot(None),
            )
            .order_by(VitalRecord.recorded_at.desc())
            .first()
        )
        if last_good:
            lcd_hr = last_good.heart_rate
            lcd_spo2 = last_good.spo2
            lcd_temp = last_good.temperature
            lcd_sys = last_good.systolic_bp
            lcd_dia = last_good.diastolic_bp

    lcd1_parts = []
    if lcd_hr is not None:
        lcd1_parts.append(f"HR: {int(lcd_hr)}")
    if lcd_spo2 is not None:
        lcd1_parts.append(f"SpO2: {int(lcd_spo2)}%")
    lcd1 = " | ".join(lcd1_parts) if lcd1_parts else "Waiting..."

    lcd2_parts = []
    if lcd_temp is not None:
        lcd2_parts.append(f"Temp: {float(lcd_temp):.1f}C")
    lcd2 = " | ".join(lcd2_parts) if lcd2_parts else "for data..."

    lcd3_parts = []
    if lcd_sys is not None and lcd_dia is not None:
        lcd3_parts.append(f"BP: {int(lcd_sys)}/{int(lcd_dia)}")
    elif lcd_sys is not None:
        lcd3_parts.append(f"BP: {int(lcd_sys)}/-")
    lcd3 = " | ".join(lcd3_parts) if lcd3_parts else (latest_notif.message[:20] if latest_notif else "")

    if sensor_error and (hr is None and spo2_val is None) and last_good and last_good.recorded_at:
        lcd4_time = last_good.recorded_at + timedelta(hours=8)
    elif latest and latest.recorded_at:
        lcd4_time = latest.recorded_at + timedelta(hours=8)
    else:
        lcd4_time = now + timedelta(hours=8)
    lcd4 = lcd4_time.strftime("%Y-%m-%d %H:%M:%S")

    led, is_alert, alert_reasons = check_vitals_alert(
        user.age, hr, spo2_val, temp_val, sys_bp, dia_bp, sensor_error=sensor_error
    )

    overrides = _debug_overrides.get(patient_id, {})
    final_smsalert = overrides.get("smsalert", False)
    final_smsalertmsg = overrides.get("smsalertmsg", "none")
    final_meddispense = overrides.get("medicinedispense", 0)
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
        "timestamp": (now + timedelta(hours=8)).isoformat(),
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
    return JSONResponse(_debug_overrides.get(patient_id, dict(DEFAULT_DEBUG_OVERRIDE)))


@router.post("/api/debug/override/{patient_id}")
async def api_set_debug_override(
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

    current = _debug_overrides.get(patient_id, dict(DEFAULT_DEBUG_OVERRIDE))
    for field in DEFAULT_DEBUG_OVERRIDE:
        if field in body:
            current[field] = body[field]

    _debug_overrides[patient_id] = current
    return JSONResponse({"status": "ok", "overrides": current})


@router.delete("/api/debug/override/{patient_id}")
def api_clear_debug_override(patient_id: int, request: Request):
    verify_api_key(request)
    _debug_overrides.pop(patient_id, None)
    return JSONResponse({"status": "cleared"})
