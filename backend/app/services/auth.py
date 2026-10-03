"""Autentikasi dashboard: hash password & token sesi bertanda tangan.

Satu pemilik, tanpa tabel pengguna: email + hash password + rahasia penanda
tangan ada di backend/.env (ditulis ops/set-password.py). Hanya pustaka standar.

Format hash : pbkdf2_sha256$<iterasi>$<salt hex>$<hash hex>
Format token: <payload base64url>.<HMAC-SHA256 base64url>
  payload   = {"sub": email, "exp": epoch_detik}
Token yang sama diverifikasi oleh proxy Next (frontend/src/proxy.ts) dengan
rahasia yang sama — perubahan format harus dilakukan di kedua tempat.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

PBKDF2_ITERATIONS = 600_000
COOKIE_NAME = "at_session"


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Hash PBKDF2-SHA256 dengan salt acak 16 byte."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Bandingkan password dengan hash tersimpan (waktu konstan)."""
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(email: str, secret: str, ttl_sec: int) -> str:
    """Token sesi bertanda tangan HMAC-SHA256."""
    payload = _b64(json.dumps({"sub": email, "exp": int(time.time()) + ttl_sec},
                              separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: str, secret: str) -> str | None:
    """Email pemilik bila token sah & belum kedaluwarsa, selain itu None."""
    if not token or not secret or token.count(".") != 1:
        return None
    payload, sig = token.split(".")
    expected = _b64(hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < time.time():
        return None
    return str(data.get("sub") or "") or None


def session_email_from_cookies(cookies: dict) -> str | None:
    """Email pemilik dari cookie sesi (dipakai WebSocket, yang tak lewat dependensi HTTP)."""
    from app.config import get_settings
    return verify_token(cookies.get(COOKIE_NAME, ""), get_settings().auth_secret)
