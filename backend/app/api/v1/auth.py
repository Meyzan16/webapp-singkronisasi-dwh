"""POST /auth/login, POST /auth/logout, GET /auth/me — login dashboard satu pemilik.

Cookie sesi `at_session` (httpOnly, SameSite=Lax) diverifikasi juga oleh proxy
Next untuk setiap halaman & /api/*. Backend sendiri hanya mendengar di 127.0.0.1
(ops/start-night.ps1), jadi satu-satunya pintu dari jaringan adalah Next.
"""

import asyncio
import hmac
import time

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import get_settings
from app.services.auth import COOKIE_NAME, issue_token, verify_password, verify_token

router = APIRouter(tags=["auth"])
logger = structlog.get_logger(__name__)

MAX_FAILS = 5                 # percobaan salah per IP …
FAIL_WINDOW_SEC = 15 * 60     # … dalam 15 menit
_fails: dict[str, list[float]] = {}


class LoginRequest(BaseModel):
    """Isian form login."""
    email: str
    password: str


class MeResponse(BaseModel):
    """Pemilik sesi aktif."""
    email: str
    name: str


def _client_ip(request: Request) -> str:
    """IP pengakses asli. Header dari Next bisa dipercaya: backend hanya di 127.0.0.1."""
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def _recent_fails(ip: str, now: float) -> list[float]:
    kept = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW_SEC]
    _fails[ip] = kept
    return kept


@router.post("/auth/login", response_model=MeResponse)
async def login(body: LoginRequest, request: Request, response: Response) -> MeResponse:
    """Periksa email + password; bila cocok pasang cookie sesi."""
    s = get_settings()
    if not (s.auth_email and s.auth_password_hash and s.auth_secret):
        raise HTTPException(status_code=503,
                            detail="Login belum disiapkan. Jalankan ops/set-password.py di laptop server.")
    ip, now = _client_ip(request), time.time()
    if len(_recent_fails(ip, now)) >= MAX_FAILS:
        logger.warning("auth_login_locked", ip=ip)
        raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Coba lagi dalam 15 menit.")

    email_ok = hmac.compare_digest(body.email.strip().lower(), s.auth_email.strip().lower())
    pw_ok = await asyncio.to_thread(verify_password, body.password, s.auth_password_hash)
    if not (email_ok and pw_ok):
        _fails.setdefault(ip, []).append(now)
        logger.warning("auth_login_failed", ip=ip, fails=len(_fails[ip]))
        raise HTTPException(status_code=401, detail="Email atau password salah.")

    _fails.pop(ip, None)
    ttl = max(1, s.auth_session_days) * 86400
    response.set_cookie(COOKIE_NAME, issue_token(s.auth_email, s.auth_secret, ttl),
                        max_age=ttl, httponly=True, samesite="lax", path="/")
    logger.info("auth_login_ok", ip=ip)
    return MeResponse(email=s.auth_email, name=s.auth_email.split("@")[0])


@router.post("/auth/logout")
async def logout(response: Response) -> dict:
    """Hapus cookie sesi."""
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=MeResponse)
async def me(request: Request) -> MeResponse:
    """Pemilik sesi aktif, atau 401."""
    s = get_settings()
    email = verify_token(request.cookies.get(COOKIE_NAME, ""), s.auth_secret)
    if not email:
        raise HTTPException(status_code=401, detail="Belum login.")
    return MeResponse(email=email, name=email.split("@")[0])
