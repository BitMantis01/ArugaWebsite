from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, VitalRecord, Medicine, Notification, LiveFeedImage
from app.routers.auth import get_current_user
from app.services.csrf_service import get_csrf_token
from app.services.vitals_service import analyze_blood_pressure_pattern

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="templates")

# Register Jinja2 global functions
templates.env.globals["now"] = datetime.utcnow
templates.env.globals["get_csrf_token"] = get_csrf_token


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse(request, "home.html", {"user": user})


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "login.html")


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "signup.html")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=302)

    vitals_desc = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == user.id)
        .order_by(VitalRecord.recorded_at.desc())
        .limit(50)
        .all()
    )

    latest_vital = vitals_desc[0] if vitals_desc else None

    # Previous 5 readings before the latest reading
    previous_5_records = vitals_desc[1:6]
    previous_readings = []
    for r in previous_5_records:
        gmt8_time = (r.recorded_at + timedelta(hours=8)) if r.recorded_at else None
        formatted_time = gmt8_time.strftime("%b %d, %Y %H:%M:%S") if gmt8_time else "--"
        previous_readings.append({
            "id": r.id,
            "real_time": formatted_time,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
            "spo2": f"{r.spo2:.1f}" if r.spo2 is not None else "--",
            "heart_rate": str(r.heart_rate) if r.heart_rate is not None else "--",
            "temperature": f"{r.temperature:.1f}" if r.temperature is not None else "--",
            "blood_pressure": f"{r.systolic_bp}/{r.diastolic_bp}" if (r.systolic_bp is not None and r.diastolic_bp is not None) else "--/--",
        })

    # Blood Pressure Pattern based on latest 5 complete blood pressure readings
    valid_bp_records = [
        r for r in vitals_desc
        if not r.sensor_error and r.systolic_bp is not None and r.diastolic_bp is not None
    ][:5]
    bp_pattern = analyze_blood_pressure_pattern(valid_bp_records)

    medicines = (
        db.query(Medicine)
        .filter(Medicine.user_id == user.id, Medicine.active == True)
        .all()
    )

    vitals_history = list(reversed(vitals_desc))
    vitals_history_json = [
        {
            "id": v.id,
            "spo2": v.spo2,
            "heart_rate": v.heart_rate,
            "temperature": v.temperature,
            "systolic_bp": v.systolic_bp,
            "diastolic_bp": v.diastolic_bp,
            "sensor_error": v.sensor_error,
            "recorded_at": v.recorded_at.isoformat() if v.recorded_at else None,
        }
        for v in vitals_history
    ]

    live_feed = (
        db.query(LiveFeedImage)
        .filter(LiveFeedImage.user_id == user.id)
        .order_by(LiveFeedImage.uploaded_at.desc())
        .limit(24)
        .all()
    )

    live_feed_json = [
        {
            "id": img.id,
            "image_path": img.image_path,
            "caption": img.caption,
            "uploaded_at": img.uploaded_at,
            "seconds_ago": int((datetime.utcnow() - img.uploaded_at).total_seconds()) if img.uploaded_at else 0,
        }
        for img in live_feed
    ]

    notifications = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(30)
        .all()
    )
    notifications_json = [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "level": n.level,
            "is_read": n.is_read,
            "created_at": n.created_at,
        }
        for n in notifications
    ]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "latest_vital": latest_vital,
            "previous_readings": previous_readings,
            "bp_pattern": bp_pattern,
            "medicines": medicines,
            "vitals_history": vitals_history_json,
            "live_feed": live_feed_json,
            "notifications": notifications_json,
        },
    )

