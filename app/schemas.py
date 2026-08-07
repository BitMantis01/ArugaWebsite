import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class UserSignup(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., max_length=255)
    age: Optional[int] = Field(None, ge=0, le=150)
    gender: Optional[str] = Field(None, max_length=50)
    blood_type: Optional[str] = Field(None, max_length=10)
    height_cm: Optional[float] = Field(None, ge=0, le=300)
    weight_kg: Optional[float] = Field(None, ge=0, le=500)
    medical_conditions: Optional[str] = Field(None, max_length=2000)
    emergency_contact_name: Optional[str] = Field(None, max_length=255)
    emergency_contact_phone: Optional[str] = Field(None, max_length=50)

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email address format")
        return v


class UserLogin(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email address format")
        return v



class ProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    age: Optional[int] = Field(None, ge=0, le=150)
    gender: Optional[str] = Field(None, max_length=50)
    blood_type: Optional[str] = Field(None, max_length=10)
    height_cm: Optional[float] = Field(None, ge=0, le=300)
    weight_kg: Optional[float] = Field(None, ge=0, le=500)
    medical_conditions: Optional[str] = Field(None, max_length=2000)
    emergency_contact_name: Optional[str] = Field(None, max_length=255)
    emergency_contact_phone: Optional[str] = Field(None, max_length=50)


class VitalsUploadPayload(BaseModel):
    spo2: Optional[float] = None
    heartrate: Optional[int] = Field(None, alias="heart_rate")
    temp: Optional[float] = Field(None, alias="temperature")
    bp_systolic: Optional[int] = Field(None, alias="bp-systolic")
    bp_diastolic: Optional[int] = Field(None, alias="bp-diastolic")
    error: Optional[bool] = False

    class Config:
        populate_by_name = True


class DebugOverridePayload(BaseModel):
    smsalert: Optional[bool] = None
    smsalertmsg: Optional[str] = Field(None, max_length=500)
    medicinedispense: Optional[int] = None
    move: Optional[bool] = None
    led: Optional[str] = Field(None, max_length=50)
    lcd3: Optional[str] = Field(None, max_length=50)
    alert: Optional[bool] = None


class MedicineSlotUpdate(BaseModel):
    slot_number: int = Field(..., ge=1, le=7)  # 1 to 7
    name: Optional[str] = Field("Empty Slot", max_length=255)
    dosage: Optional[str] = Field("", max_length=100)
    scheduled_datetime: Optional[str] = None  # e.g. "2026-07-29T18:30"
    active: Optional[bool] = False
    is_dispensed: Optional[bool] = False


