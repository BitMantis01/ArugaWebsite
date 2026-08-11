from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text, Index
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    age = Column(Integer, nullable=True)
    gender = Column(String(50), nullable=True)
    blood_type = Column(String(10), nullable=True)
    height_cm = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)
    medical_conditions = Column(Text, nullable=True)
    emergency_contact_name = Column(String(255), nullable=True)
    emergency_contact_phone = Column(String(50), nullable=True)
    enable_sms_alerts = Column(Boolean, default=True, nullable=False)
    last_sms_alert_no = Column(Integer, default=0, nullable=False)
    last_sms_alert_time = Column(DateTime, nullable=True)
    last_sms_alert_vital_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    vitals = relationship("VitalRecord", back_populates="user")
    medicines = relationship("Medicine", back_populates="user")
    notifications = relationship("Notification", back_populates="user")
    live_feed_images = relationship("LiveFeedImage", back_populates="user")


class VitalRecord(Base):
    __tablename__ = "vital_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    spo2 = Column(Float, nullable=True)           # Blood oxygen %
    heart_rate = Column(Integer, nullable=True)    # BPM
    temperature = Column(Float, nullable=True)     # Celsius
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)
    sensor_error = Column(Boolean, default=False)  # True = no finger / poor reading
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="vitals")

    __table_args__ = (
        Index("idx_vital_user_time", "user_id", "recorded_at"),
    )


class Medicine(Base):
    __tablename__ = "medicines"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    slot_number = Column(Integer, nullable=False, default=1, index=True)  # 1 to 7
    name = Column(String(255), nullable=False, default="Empty Slot")
    dosage = Column(String(100), nullable=True, default="")
    frequency = Column(String(100), nullable=True, default="")
    scheduled_time = Column(String(100), nullable=True)
    scheduled_datetime = Column(DateTime, nullable=True)  # GMT+8 target datetime
    is_dispensed = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    active = Column(Boolean, default=False)

    user = relationship("User", back_populates="medicines")



class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    level = Column(String(50), default="info")  # info, warning, critical
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="notifications")

    __table_args__ = (
        Index("idx_notif_user_time", "user_id", "created_at"),
    )


class LiveFeedImage(Base):
    __tablename__ = "live_feed_images"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    image_path = Column(String(500), nullable=True)  # relative path to stored JPEG file
    caption = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="live_feed_images")

    @property
    def url(self) -> str:
        from app.services.storage_service import get_presigned_or_public_url
        return get_presigned_or_public_url(self)

    __table_args__ = (
        Index("idx_livefeed_user_time", "user_id", "uploaded_at"),
    )
