import os
import logging
from pathlib import Path
from typing import Optional
try:
    import boto3
    from botocore.config import Config
    HAS_BOTO3 = True
except ImportError:
    boto3 = None
    Config = None
    HAS_BOTO3 = False
from sqlalchemy.orm import Session

from app.config import (
    BASE_DIR,
    UPLOAD_DIR,
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
    R2_PUBLIC_URL,
    MAX_LIVE_FEED_IMAGES_PER_USER,
)
from app.models import LiveFeedImage

logger = logging.getLogger(__name__)


def is_r2_configured() -> bool:
    """Check if Cloudflare R2 environment credentials and boto3 are fully provided."""
    return bool(HAS_BOTO3 and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME and R2_ACCOUNT_ID)


def get_r2_client():
    """Build S3 client for Cloudflare R2 using boto3."""
    if not is_r2_configured():
        return None
    endpoint_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def upload_live_feed_image(user_id: int, filename: str, image_bytes: bytes) -> str:
    """
    Upload snapshot bytes to Cloudflare R2 (or fallback to local disk).
    Returns object key or relative local path.
    """
    object_key = f"live_feed/{user_id}/{filename}"

    if is_r2_configured():
        try:
            s3 = get_r2_client()
            s3.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=object_key,
                Body=image_bytes,
                ContentType="image/jpeg",
                CacheControl="private, max-age=3600" if not R2_PUBLIC_URL else "public, max-age=31536000",
            )
            # Store object key in database (or public URL if R2_PUBLIC_URL is configured)
            if R2_PUBLIC_URL:
                return f"{R2_PUBLIC_URL.rstrip('/')}/{object_key}"
            return object_key
        except Exception as e:
            logger.error(f"Failed to upload image to R2 ({object_key}), using local fallback: {e}")

    # Fallback to local storage
    patient_dir = UPLOAD_DIR / str(user_id)
    os.makedirs(patient_dir, exist_ok=True)
    file_path = patient_dir / filename
    with open(file_path, "wb") as f:
        f.write(image_bytes)

    return f"uploads/live_feed/{user_id}/{filename}"


def get_presigned_or_public_url(image_record: LiveFeedImage, expires_in: int = 3600) -> str:
    """
    Returns image access URL.
    - If R2_PUBLIC_URL is set, returns public CDN URL.
    - If R2 is private (no R2_PUBLIC_URL), generates a temporary presigned URL (valid for 1 hour).
    - If local file, returns relative static URL (/static/uploads/live_feed/...).
    """
    if not image_record or not image_record.image_path:
        return ""

    path_str = image_record.image_path

    # If R2_PUBLIC_URL is configured
    if R2_PUBLIC_URL:
        if path_str.startswith("http://") or path_str.startswith("https://"):
            return path_str
        return f"{R2_PUBLIC_URL.rstrip('/')}/{path_str.lstrip('/')}"

    # If Cloudflare R2 is configured and private -> Generate temporary presigned S3 URL
    if is_r2_configured():
        try:
            if "live_feed/" in path_str:
                object_key = "live_feed/" + path_str.rsplit("live_feed/", 1)[1]
            else:
                object_key = path_str

            s3 = get_r2_client()
            presigned_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": R2_BUCKET_NAME, "Key": object_key},
                ExpiresIn=expires_in,
            )
            return presigned_url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL ({path_str}): {e}")

    # Fallback for local files
    if path_str.startswith("http://") or path_str.startswith("https://"):
        return path_str
    return f"/static/{path_str.lstrip('/')}"


def delete_live_feed_image(image_record: LiveFeedImage) -> None:
    """Delete image file from Cloudflare R2 or local filesystem."""
    if not image_record or not image_record.image_path:
        return

    path_str = image_record.image_path

    if is_r2_configured():
        try:
            prefix = f"live_feed/{image_record.user_id}/"
            if prefix in path_str:
                filename = path_str.rsplit(prefix, 1)[1]
                object_key = f"{prefix}{filename}"
            else:
                object_key = path_str

            s3 = get_r2_client()
            s3.delete_object(Bucket=R2_BUCKET_NAME, Key=object_key)
            return
        except Exception as e:
            logger.error(f"Failed to delete R2 object ({path_str}): {e}")

    # Local file deletion fallback
    try:
        full_path = BASE_DIR / "static" / path_str.lstrip("/")
        if full_path.exists():
            os.remove(full_path)
    except Exception as e:
        logger.error(f"Failed to delete local image ({path_str}): {e}")


def enforce_account_image_limit(user_id: int, db: Session, max_limit: int = MAX_LIVE_FEED_IMAGES_PER_USER) -> int:
    """
    Enforce max 150 live-feed images per account.
    Deletes oldest excess images from R2 and database.
    """
    count = db.query(LiveFeedImage).filter(LiveFeedImage.user_id == user_id).count()
    if count < max_limit:
        return 0

    excess = count - max_limit + 1
    if excess <= 0:
        return 0

    oldest_records = (
        db.query(LiveFeedImage)
        .filter(LiveFeedImage.user_id == user_id)
        .order_by(LiveFeedImage.uploaded_at.asc())
        .limit(excess)
        .all()
    )

    deleted_count = 0
    for rec in oldest_records:
        delete_live_feed_image(rec)
        db.delete(rec)
        deleted_count += 1

    db.commit()
    return deleted_count
