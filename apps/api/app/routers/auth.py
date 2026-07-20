import hmac
import os
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth import COOKIE_NAME, SESSION_TTL_SECONDS, create_session_token, request_is_authenticated


router = APIRouter(prefix="/auth", tags=["auth"])
_attempts: dict[str, deque[float]] = defaultdict(deque)
ATTEMPT_WINDOW = 300
MAX_ATTEMPTS = 5


class LoginRequest(BaseModel):
    access_key: str


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = _attempts[client]
    while attempts and now - attempts[0] > ATTEMPT_WINDOW:
        attempts.popleft()
    if len(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 5 minutos.")

    expected = os.getenv("WORKDEV_API_KEY")
    if not expected or not hmac.compare_digest(payload.access_key, expected):
        attempts.append(now)
        raise HTTPException(status_code=401, detail="Chave de acesso inválida")

    attempts.clear()
    secure = os.getenv("WORKDEV_COOKIE_SECURE", "true").lower() != "false"
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    return {"authenticated": True}


@router.get("/me")
def me(request: Request):
    if not request_is_authenticated(request):
        raise HTTPException(status_code=401, detail="Não autenticado")
    return {"authenticated": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"authenticated": False}
