import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Base directory (Workspace root)
BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent

# Load environment variables from .env if present
env_path = BASE_DIR / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path)
except ImportError:
    # Fallback zero-dependency .env loader
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key not in os.environ:
                        os.environ[key] = val

# Environment Configuration Variables
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
API_KEY = os.getenv("ARUGA_API_KEY", "aruga-dev-key-change-in-production")
SECRET_KEY = os.getenv("SECRET_KEY", "aruga-secret-key-change-in-production-2026")

if ENVIRONMENT == "production":
    if API_KEY == "aruga-dev-key-change-in-production":
        raise ValueError("CRITICAL SECURITY ERROR: ARUGA_API_KEY must be set in production environment!")
    if SECRET_KEY == "aruga-secret-key-change-in-production-2026":
        raise ValueError("CRITICAL SECURITY ERROR: SECRET_KEY must be set in production environment!")
else:
    if API_KEY == "aruga-dev-key-change-in-production" or SECRET_KEY == "aruga-secret-key-change-in-production-2026":
        logger.warning("WARNING: Using default development API_KEY or SECRET_KEY. Change these in .env before deploying to production.")

ENABLE_DEBUG_ENDPOINTS = os.getenv("ENABLE_DEBUG_ENDPOINTS", "true" if ENVIRONMENT == "development" else "false").lower() == "true"
ENABLE_API_DOCS = os.getenv("ENABLE_API_DOCS", "true" if ENVIRONMENT == "development" else "false").lower() == "true"

UPLOAD_DIR = BASE_DIR / "static" / "uploads" / "live_feed"
PARAMETER_PATH = APP_DIR / "parameter.json"

# Cloudflare R2 Storage Settings
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")

# Live Feed Storage Quotas & Cost-Protection Rate Limits
MAX_LIVE_FEED_IMAGES_PER_USER = int(os.getenv("MAX_LIVE_FEED_IMAGES_PER_USER", "150"))
LIVE_FEED_MIN_SAVE_INTERVAL_SECONDS = float(os.getenv("LIVE_FEED_MIN_SAVE_INTERVAL_SECONDS", "3.0"))

