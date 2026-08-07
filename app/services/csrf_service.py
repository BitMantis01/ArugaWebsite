import secrets
import hmac
from fastapi import Request, HTTPException, Depends


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def get_csrf_token(request: Request) -> str:
    """Ensure a CSRF token exists in session and return it."""
    token = request.session.get("csrf_token")
    if not token:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
    return token


async def verify_csrf_token(request: Request):
    """
    Verify CSRF token for state-changing HTTP methods.
    Exempts API requests presenting a valid x-api-key header.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # Exempt hardware requests authenticated via x-api-key
    from app.config import API_KEY
    key = request.headers.get("x-api-key")
    if key and hmac.compare_digest(key, API_KEY):
        return

    session_token = request.session.get("csrf_token")
    if not session_token:
        raise HTTPException(status_code=403, detail="CSRF token missing from session")

    client_token = request.headers.get("x-csrf-token")

    if not client_token:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                json_data = await request.json()
                client_token = json_data.get("csrf_token")
            except Exception:
                pass
        elif "form" in content_type:
            try:
                form_data = await request.form()
                client_token = form_data.get("csrf_token")
            except Exception:
                pass

    if not client_token or not hmac.compare_digest(str(client_token), session_token):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")
