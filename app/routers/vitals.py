import csv
import io
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, VitalRecord, Notification, Medicine
from app.schemas import ProfileUpdate, MedicineSlotUpdate

from app.routers.auth import require_user, get_current_user
from app.services.prediction_service import get_vitals_predictions

router = APIRouter(tags=["vitals"])


@router.get("/api/vitals/latest")
def api_vitals_latest(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    record = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == user.id)
        .order_by(VitalRecord.recorded_at.desc())
        .first()
    )
    if not record:
        return JSONResponse({"has_data": False})

    return JSONResponse({
        "has_data": True,
        "id": record.id,
        "spo2": record.spo2,
        "heart_rate": record.heart_rate,
        "temperature": record.temperature,
        "systolic_bp": record.systolic_bp,
        "diastolic_bp": record.diastolic_bp,
        "sensor_error": record.sensor_error,
        "recorded_at": record.recorded_at.isoformat(),
        "seconds_ago": int((datetime.utcnow() - record.recorded_at).total_seconds()),
    })


@router.get("/api/vitals/history")
def api_vitals_history(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    records = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == user.id)
        .order_by(VitalRecord.recorded_at.desc())
        .limit(limit)
        .all()
    )
    records.reverse()

    return JSONResponse([
        {
            "id": r.id,
            "spo2": r.spo2,
            "heart_rate": r.heart_rate,
            "temperature": r.temperature,
            "systolic_bp": r.systolic_bp,
            "diastolic_bp": r.diastolic_bp,
            "sensor_error": r.sensor_error,
            "recorded_at": r.recorded_at.isoformat(),
        }
        for r in records
    ])


@router.get("/api/vitals/export")
def api_export_vitals(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    records = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == user.id)
        .order_by(VitalRecord.recorded_at.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Record ID",
        "Timestamp (UTC)",
        "SpO2 (%)",
        "Heart Rate (BPM)",
        "Temperature (C)",
        "Systolic BP (mmHg)",
        "Diastolic BP (mmHg)",
        "Sensor Error"
    ])

    for r in records:
        writer.writerow([
            r.id,
            r.recorded_at.isoformat() if r.recorded_at else "",
            r.spo2 if r.spo2 is not None else "",
            r.heart_rate if r.heart_rate is not None else "",
            r.temperature if r.temperature is not None else "",
            r.systolic_bp if r.systolic_bp is not None else "",
            r.diastolic_bp if r.diastolic_bp is not None else "",
            "Yes" if r.sensor_error else "No"
        ])

    csv_content = output.getvalue()
    filename = f"aruga_vitals_user_{user.id}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/api/predictions")
def api_predictions(
    request: Request,
    steps: int = Query(20, ge=5, le=50),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    raw_records = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == user.id, VitalRecord.sensor_error == False)
        .order_by(VitalRecord.recorded_at.desc())
        .limit(100)
        .all()
    )
    raw_records.reverse()

    # Filter strictly to records with ALL vitals present
    records = [
        r for r in raw_records
        if r.spo2 is not None
        and r.heart_rate is not None
        and r.temperature is not None
        and r.systolic_bp is not None
        and r.diastolic_bp is not None
    ]

    spo2_h = [r.spo2 for r in records]
    hr_h = [r.heart_rate for r in records]
    temp_h = [r.temperature for r in records]
    sys_bp_h = [r.systolic_bp for r in records]
    dia_bp_h = [r.diastolic_bp for r in records]

    results = get_vitals_predictions(spo2_h, hr_h, temp_h, sys_bp_h, dia_bp_h, steps=steps)

    last_time = raw_records[-1].recorded_at if raw_records else datetime.utcnow()
    future_times = [(last_time + timedelta(seconds=15 * (i + 1))).isoformat() for i in range(steps)]
    results["future_times"] = future_times

    return JSONResponse(results)


@router.get("/api/notifications")
def api_notifications(
    request: Request,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    notifs = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return JSONResponse([
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "level": n.level,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifs
    ])


@router.post("/api/notifications/{notif_id}/read")
def api_mark_notification_read(
    notif_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    notif = (
        db.query(Notification)
        .filter(Notification.id == notif_id, Notification.user_id == user.id)
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif.is_read = True
    db.commit()
    return JSONResponse({"status": "ok", "id": notif_id})


@router.get("/api/profile")
def api_get_profile(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return JSONResponse({
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "age": user.age,
        "gender": user.gender,
        "blood_type": user.blood_type,
        "height_cm": user.height_cm,
        "weight_kg": user.weight_kg,
        "medical_conditions": user.medical_conditions,
        "emergency_contact_name": user.emergency_contact_name,
        "emergency_contact_phone": user.emergency_contact_phone,
    })


@router.patch("/api/profile")
def api_update_profile(
    data: ProfileUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    for field, val in data.model_dump(exclude_unset=True).items():
        if hasattr(user, field):
            setattr(user, field, val)

    db.commit()
    db.refresh(user)
    return JSONResponse({"status": "ok", "message": "Profile updated successfully"})


def ensure_user_medicine_slots(user_id: int, db: Session) -> List[Medicine]:
    """Ensure user has exactly 7 slots (1 to 7) in database."""
    existing = db.query(Medicine).filter(Medicine.user_id == user_id).all()
    by_slot = {m.slot_number: m for m in existing if m.slot_number}

    updated = False
    for slot in range(1, 8):
        if slot not in by_slot:
            med = Medicine(
                user_id=user_id,
                slot_number=slot,
                name=f"Medicine Slot {slot}",
                dosage="",
                active=False,
                is_dispensed=False,
            )
            db.add(med)
            updated = True

    if updated:
        db.commit()

    return (
        db.query(Medicine)
        .filter(Medicine.user_id == user_id)
        .order_by(Medicine.slot_number.asc())
        .all()
    )


@router.get("/api/medicines")
def api_get_medicines(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    slots = ensure_user_medicine_slots(user.id, db)
    return JSONResponse([
        {
            "id": s.id,
            "slot_number": s.slot_number,
            "name": s.name,
            "dosage": s.dosage,
            "active": s.active,
            "is_dispensed": s.is_dispensed,
            "scheduled_datetime": s.scheduled_datetime.isoformat() if s.scheduled_datetime else None,
        }
        for s in slots
    ])


@router.post("/api/medicines/slot")
def api_update_medicine_slot(
    payload: MedicineSlotUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not (1 <= payload.slot_number <= 7):
        raise HTTPException(status_code=400, detail="Slot number must be between 1 and 7")

    slots = ensure_user_medicine_slots(user.id, db)
    slot_obj = next((s for s in slots if s.slot_number == payload.slot_number), None)
    if not slot_obj:
        raise HTTPException(status_code=404, detail="Slot not found")

    slot_obj.name = payload.name.strip() if payload.name else f"Medicine Slot {payload.slot_number}"
    slot_obj.dosage = payload.dosage.strip() if payload.dosage else ""
    slot_obj.active = bool(payload.active)
    slot_obj.is_dispensed = bool(payload.is_dispensed)

    if payload.scheduled_datetime:
        try:
            # Parse datetime string e.g. "2026-07-29T18:30"
            dt_str = payload.scheduled_datetime.replace("Z", "")
            slot_obj.scheduled_datetime = datetime.fromisoformat(dt_str)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid datetime format")
    else:
        slot_obj.scheduled_datetime = None

    db.commit()
    db.refresh(slot_obj)

    return JSONResponse({
        "status": "ok",
        "message": f"Medicine Slot {payload.slot_number} updated",
        "slot": {
            "slot_number": slot_obj.slot_number,
            "name": slot_obj.name,
            "dosage": slot_obj.dosage,
            "active": slot_obj.active,
            "is_dispensed": slot_obj.is_dispensed,
            "scheduled_datetime": slot_obj.scheduled_datetime.isoformat() if slot_obj.scheduled_datetime else None,
        }
    })


@router.post("/api/medicines/slot/{slot_number}/reset")
def api_reset_medicine_slot(
    slot_number: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not (1 <= slot_number <= 7):
        raise HTTPException(status_code=400, detail="Slot number must be between 1 and 7")

    slots = ensure_user_medicine_slots(user.id, db)
    slot_obj = next((s for s in slots if s.slot_number == slot_number), None)
    if slot_obj:
        slot_obj.name = f"Medicine Slot {slot_number}"
        slot_obj.dosage = ""
        slot_obj.scheduled_datetime = None
        slot_obj.active = False
        slot_obj.is_dispensed = False
        db.commit()

    return JSONResponse({"status": "ok", "message": f"Slot {slot_number} reset"})

