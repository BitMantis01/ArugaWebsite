import os
from pathlib import Path

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
API_KEY = os.getenv("ARUGA_API_KEY", "aruga-dev-key-change-in-production")
SECRET_KEY = os.getenv("SECRET_KEY", "aruga-secret-key-change-in-production-2026")
UPLOAD_DIR = BASE_DIR / "static" / "uploads" / "live_feed"
PARAMETER_PATH = APP_DIR / "parameter.json"
