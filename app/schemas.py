from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


class UserSignup(BaseModel):
    email: str
    password: str
    full_name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    blood_type: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    medical_conditions: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class UserLogin(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    blood_type: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    medical_conditions: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


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
    smsalertmsg: Optional[str] = None
    medicinedispense: Optional[int] = None
    move: Optional[bool] = None
    led: Optional[str] = None
    lcd3: Optional[str] = None
    alert: Optional[bool] = None


class MedicineSlotUpdate(BaseModel):
    slot_number: int  # 1 to 7
    name: Optional[str] = "Empty Slot"
    dosage: Optional[str] = ""
    scheduled_datetime: Optional[str] = None  # e.g. "2026-07-29T18:30"
    active: Optional[bool] = False
    is_dispensed: Optional[bool] = False

