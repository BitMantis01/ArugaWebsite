from datetime import datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, VitalRecord, Medicine, Notification, LiveFeedImage
from app.routers.auth import get_current_user

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="templates")

# Register Jinja2 global functions
templates.env.globals["now"] = datetime.utcnow


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "home.html")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse(request, "signup.html")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=302)

    latest_vital = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == user.id)
        .order_by(VitalRecord.recorded_at.desc())
        .first()
    )

    medicines = (
        db.query(Medicine)
        .filter(Medicine.user_id == user.id, Medicine.active == True)
        .all()
    )

    vitals_history = (
        db.query(VitalRecord)
        .filter(VitalRecord.user_id == user.id)
        .order_by(VitalRecord.recorded_at.desc())
        .limit(50)
        .all()
    )
    vitals_history.reverse()

    vitals_history_json = [
        {
            "spo2": v.spo2,
            "heart_rate": v.heart_rate,
            "temperature": v.temperature,
            "systolic_bp": v.systolic_bp,
            "diastolic_bp": v.diastolic_bp,
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
            "medicines": medicines,
            "vitals_history": vitals_history_json,
            "live_feed": live_feed_json,
            "notifications": notifications_json,
        },
    )
