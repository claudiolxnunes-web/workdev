import base64
import hashlib
import hmac
import os
import time

from fastapi import Request, WebSocket


COOKIE_NAME = "workdev_session"
SESSION_TTL_SECONDS = int(os.getenv("WORKDEV_SESSION_TTL_SECONDS", "43200"))


def _secret() -> bytes:
    value = os.getenv("WORKDEV_SESSION_SECRET")
    if not value:
        raise RuntimeError("WORKDEV_SESSION_SECRET não configurada")
    return value.encode()


def create_session_token() -> str:
    timestamp = str(int(time.time()))
    signature = hmac.new(_secret(), timestamp.encode(), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{timestamp}.{encoded}"


def validate_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        timestamp_text, signature = token.split(".", 1)
        timestamp = int(timestamp_text)
    except (ValueError, TypeError):
        return False
    now = int(time.time())
    if timestamp > now + 60 or now - timestamp > SESSION_TTL_SECONDS:
        return False
    expected = base64.urlsafe_b64encode(
        hmac.new(_secret(), timestamp_text.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return hmac.compare_digest(signature, expected)


def request_is_authenticated(request: Request) -> bool:
    if validate_session_token(request.cookies.get(COOKIE_NAME)):
        return True
    api_key = os.getenv("WORKDEV_API_KEY")
    supplied = request.headers.get("X-API-Key")
    return bool(api_key and supplied and hmac.compare_digest(supplied, api_key))


def websocket_is_authenticated(websocket: WebSocket) -> bool:
    return validate_session_token(websocket.cookies.get(COOKIE_NAME))
