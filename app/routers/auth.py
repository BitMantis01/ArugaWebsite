from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import bcrypt

from app.database import get_db
from app.models import User
from app.schemas import UserSignup, UserLogin

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
    payload = await parse_request_data(request)
    email = str(payload.get("email", "")).lower().strip()
    password = str(payload.get("password", ""))
    full_name = str(payload.get("full_name", "")).strip()

    if not email or not password or not full_name:
        raise HTTPException(status_code=400, detail="Email, password, and full name are required")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email is already registered")

    def safe_int(v):
        try: return int(v) if v is not None and str(v).strip() != "" else None
        except: return None

    def safe_float(v):
        try: return float(v) if v is not None and str(v).strip() != "" else None
        except: return None

    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        age=safe_int(payload.get("age")),
        gender=payload.get("gender") or None,
        blood_type=payload.get("blood_type") or None,
        height_cm=safe_float(payload.get("height_cm")),
        weight_kg=safe_float(payload.get("weight_kg")),
        medical_conditions=payload.get("medical_conditions") or None,
        emergency_contact_name=payload.get("emergency_contact_name") or None,
        emergency_contact_phone=payload.get("emergency_contact_phone") or None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    request.session["user_id"] = user.id
    return JSONResponse({"status": "ok", "user_id": user.id, "message": "Account created successfully"}, status_code=201)


@router.post("/api/login")
async def api_login(request: Request, db: Session = Depends(get_db)):
    payload = await parse_request_data(request)
    email = str(payload.get("email", "")).lower().strip()
    password = str(payload.get("password", ""))

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    request.session["user_id"] = user.id
    return JSONResponse({"status": "ok", "user_id": user.id, "message": "Logged in successfully"})


@router.get("/api/logout")
def api_logout(request: Request):
    request.session.clear()
    return JSONResponse({"status": "ok", "message": "Logged out successfully"})
