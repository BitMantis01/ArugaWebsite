from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, VitalRecord, Notification
from app.schemas import ProfileUpdate
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


@router.get("/api/predictions")
def api_predictions(
    request: Request,
    steps: int = Query(20, ge=5, le=50),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    records = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == user.id, VitalRecord.sensor_error == False)
        .order_by(VitalRecord.recorded_at.desc())
        .limit(100)
        .all()
    )
    records.reverse()

    spo2_h = [r.spo2 for r in records if r.spo2 is not None]
    hr_h = [r.heart_rate for r in records if r.heart_rate is not None]
    temp_h = [r.temperature for r in records if r.temperature is not None]
    sys_bp_h = [r.systolic_bp for r in records if r.systolic_bp is not None]
    dia_bp_h = [r.diastolic_bp for r in records if r.diastolic_bp is not None]

    results = get_vitals_predictions(spo2_h, hr_h, temp_h, sys_bp_h, dia_bp_h, steps=steps)

    last_time = records[-1].recorded_at if records else datetime.utcnow()
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
