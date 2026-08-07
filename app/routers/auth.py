import html
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
import bcrypt

from app.database import get_db
from app.models import User
from app.schemas import UserSignup, UserLogin
from app.services.rate_limiter import auth_limiter, signup_limiter
from app.services.csrf_service import generate_csrf_token

router = APIRouter(tags=["auth"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get("user_id")
    if user_id is None or db is None:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return user


async def parse_request_data(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return await request.json()
        except Exception:
            return {}
    try:
        form_data = await request.form()
        return dict(form_data)
    except Exception:
        try:
            return await request.json()
        except Exception:
            return {}


@router.post("/api/signup")
async def api_signup(request: Request, db: Session = Depends(get_db)):
    signup_limiter.check(request, "signup")

    raw_payload = await parse_request_data(request)
    try:
        data = UserSignup(**raw_payload)
    except ValidationError as e:
        error_msg = e.errors()[0].get("msg", "Invalid input data")
        raise HTTPException(status_code=400, detail=error_msg)

    email = data.email.strip().lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email is already registered")

    # HTML-escape full name to prevent XSS injection
    sanitized_full_name = html.escape(data.full_name.strip())

    user = User(
        email=email,
        password_hash=hash_password(data.password),
        full_name=sanitized_full_name,
        age=data.age,
        gender=data.gender,
        blood_type=data.blood_type,
        height_cm=data.height_cm,
        weight_kg=data.weight_kg,
        medical_conditions=html.escape(data.medical_conditions) if data.medical_conditions else None,
        emergency_contact_name=html.escape(data.emergency_contact_name) if data.emergency_contact_name else None,
        emergency_contact_phone=data.emergency_contact_phone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Session fixation defense: regenerate session cleanly upon signup
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["csrf_token"] = generate_csrf_token()

    return JSONResponse({
        "status": "ok",
        "user_id": user.id,
        "message": "Account created successfully",
        "csrf_token": request.session["csrf_token"]
    }, status_code=201)


@router.post("/api/login")
async def api_login(request: Request, db: Session = Depends(get_db)):
    auth_limiter.check(request, "login")

    raw_payload = await parse_request_data(request)
    try:
        data = UserLogin(**raw_payload)
    except ValidationError as e:
        error_msg = e.errors()[0].get("msg", "Invalid email or password format")
        raise HTTPException(status_code=400, detail=error_msg)

    email = data.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Session fixation defense: clear old unauthenticated session and issue new token
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["csrf_token"] = generate_csrf_token()

    return JSONResponse({
        "status": "ok",
        "user_id": user.id,
        "message": "Logged in successfully",
        "csrf_token": request.session["csrf_token"]
    })


@router.post("/api/logout")
def api_logout(request: Request):
    request.session.clear()
    return JSONResponse({"status": "ok", "message": "Logged out successfully"})


