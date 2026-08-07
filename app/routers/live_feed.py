import os
import json
import time
import hmac
from datetime import datetime
from typing import Dict, Set
from fastapi import APIRouter, Request, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import (
    API_KEY,
    UPLOAD_DIR,
    LIVE_FEED_MIN_SAVE_INTERVAL_SECONDS,
    MAX_LIVE_FEED_IMAGES_PER_USER,
)
from app.database import SessionLocal, get_db
from app.models import User, LiveFeedImage
from app.routers.auth import require_user
from app.services.storage_service import (
    upload_live_feed_image,
    enforce_account_image_limit,
)

router = APIRouter(tags=["live_feed"])


class ConnectionManager:
    """Manages WebSocket connections: ESP32 senders + dashboard viewers."""

    def __init__(self):
        # patient_id -> set of dashboard viewer WebSockets
        self.viewers: Dict[int, Set[WebSocket]] = {}

    def connect_viewer(self, patient_id: int, ws: WebSocket):
        self.viewers.setdefault(patient_id, set()).add(ws)

    def disconnect_viewer(self, patient_id: int, ws: WebSocket):
        if patient_id in self.viewers:
            self.viewers[patient_id].discard(ws)
            if not self.viewers[patient_id]:
                del self.viewers[patient_id]

    async def broadcast_image(self, patient_id: int, data: dict):
        """Push new image info to all dashboard viewers of this patient."""
        msg = json.dumps(data)
        stale = set()
        for ws in self.viewers.get(patient_id, set()):
            try:
                await ws.send_text(msg)
            except Exception:
                stale.add(ws)
        for ws in stale:
            self.disconnect_viewer(patient_id, ws)


manager = ConnectionManager()
# Rate-limiting tracker: patient_id -> timestamp of last saved frame
last_saved_time: Dict[int, float] = {}


@router.websocket("/ws/server/image/{patient_id}")
async def ws_server_image(patient_id: int, ws: WebSocket):
    await ws.accept()

    try:
        auth_msg = await ws.receive_text()
    except WebSocketDisconnect:
        return

    key = auth_msg.strip()
    if key.lower().startswith("x-api-key:"):
        key = key.split(":", 1)[1].strip()

    if not hmac.compare_digest(key, API_KEY):
        await ws.send_text("ERROR: Invalid API key")
        await ws.close(code=4001)
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == patient_id).first()
        if not user:
            await ws.send_text("ERROR: Patient not found")
            await ws.close(code=4004)
            return
    finally:
        db.close()

    await ws.send_text("OK: Authenticated")

    while True:
        try:
            data = await ws.receive_bytes()
        except WebSocketDisconnect:
            break

        if not data or len(data) < 3 or data[:3] != b"\xff\xd8\xff":
            continue  # skip non-JPEG

        # --- Cost Protection Rate-Limiting ---
        current_time = time.time()
        last_time = last_saved_time.get(patient_id, 0.0)
        if (current_time - last_time) < LIVE_FEED_MIN_SAVE_INTERVAL_SECONDS:
            # Frame arrived too fast: skip saving to R2/DB to save Class A operations and bandwidth
            continue

        last_saved_time[patient_id] = current_time

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}.jpg"
        now = datetime.utcnow()

        db = SessionLocal()
        try:
            # 1. Enforce max 150 images per account quota (deletes oldest excess images)
            enforce_account_image_limit(patient_id, db, max_limit=MAX_LIVE_FEED_IMAGES_PER_USER)

            # 2. Upload to Cloudflare R2 (or fallback to local disk)
            stored_url_or_path = upload_live_feed_image(patient_id, filename, data)

            image_record = LiveFeedImage(
                user_id=patient_id,
                image_path=stored_url_or_path,
                caption=f"Snapshot {timestamp}",
                uploaded_at=now,
            )
            db.add(image_record)
            db.commit()
            db.refresh(image_record)

            # 3. Broadcast new image to active dashboard viewers
            await manager.broadcast_image(patient_id, {
                "type": "new_image",
                "id": image_record.id,
                "image_path": image_record.url,
                "caption": image_record.caption,
                "uploaded_at": now.isoformat(),
                "seconds_ago": 0,
            })
        finally:
            db.close()


@router.websocket("/ws/live-feed")
async def ws_live_feed(ws: WebSocket):
    await ws.accept()

    try:
        token_msg = await ws.receive_text()
    except WebSocketDisconnect:
        return

    if not token_msg.startswith("patient_id:"):
        await ws.send_text("ERROR: Send 'patient_id:ID' to subscribe")
        await ws.close(code=4000)
        return

    try:
        patient_id = int(token_msg.split(":", 1)[1].strip())
    except ValueError:
        await ws.send_text("ERROR: Invalid patient ID")
        await ws.close(code=4000)
        return

    # Session authentication check
    session_user_id = ws.session.get("user_id") if hasattr(ws, "session") else None
    if not session_user_id or session_user_id != patient_id:
        await ws.send_text("ERROR: Unauthorized session")
        await ws.close(code=4003)
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == patient_id).first()
        if not user:
            await ws.send_text("ERROR: Patient not found")
            await ws.close(code=4004)
            return
    finally:
        db.close()

    manager.connect_viewer(patient_id, ws)
    await ws.send_text("OK: Subscribed to live feed")

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_viewer(patient_id, ws)



@router.get("/api/live-feed")
def api_live_feed(
    request: Request,
    limit: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    images = (
        db.query(LiveFeedImage)
        .filter(LiveFeedImage.user_id == user.id)
        .order_by(LiveFeedImage.uploaded_at.desc())
        .limit(limit)
        .all()
    )
    now = datetime.utcnow()
    return JSONResponse([
        {
            "id": img.id,
            "image_path": img.url,
            "caption": img.caption,
            "uploaded_at": img.uploaded_at.isoformat(),
            "seconds_ago": int((now - img.uploaded_at).total_seconds()) if img.uploaded_at else 0,
        }
        for img in images
    ])
