"""Autentikasi dashboard: hash password, token sesi, endpoint login."""


import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import auth as A


def test_hash_dan_verifikasi_password():
    h = A.hash_password("rahasia-panjang-1", iterations=1000)
    assert h.startswith("pbkdf2_sha256$1000$")
    assert "rahasia" not in h
    assert A.verify_password("rahasia-panjang-1", h)
    assert not A.verify_password("rahasia-panjang-2", h)
    assert not A.verify_password("x", "rusak")


def test_token_sah_kedaluwarsa_dan_dipalsukan():
    t = A.issue_token("pemilik@contoh.id", "s" * 64, 60)
    assert A.verify_token(t, "s" * 64) == "pemilik@contoh.id"
    assert A.verify_token(t, "x" * 64) is None                       # rahasia lain
    payload, sig = t.split(".")
    assert A.verify_token(payload[:-2] + "AA." + sig, "s" * 64) is None   # payload diubah
    expired = A.issue_token("pemilik@contoh.id", "s" * 64, -5)
    assert A.verify_token(expired, "s" * 64) is None
    assert A.verify_token("", "s" * 64) is None
    assert A.verify_token(t, "") is None                              # tanpa rahasia → tolak


@pytest.fixture()
def client(monkeypatch):
    from app.api.v1 import auth as api
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "auth_email", "pemilik@contoh.id")
    monkeypatch.setattr(s, "auth_password_hash", A.hash_password("password-uji-123", iterations=1000))
    monkeypatch.setattr(s, "auth_secret", "k" * 64)
    api._fails.clear()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    return TestClient(app)


def test_login_benar_memasang_cookie_httponly(client):
    r = client.post("/api/v1/auth/login", json={"email": "Pemilik@Contoh.id", "password": "password-uji-123"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "at_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert client.get("/api/v1/auth/me").json()["email"] == "pemilik@contoh.id"


def test_login_salah_ditolak_lalu_dikunci(client):
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": "pemilik@contoh.id", "password": "salah"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "pemilik@contoh.id", "password": "password-uji-123"})
    assert r.status_code == 429                                        # terkunci walau password kini benar


def test_me_tanpa_sesi_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_belum_disiapkan_503(monkeypatch):
    from app.api.v1 import auth as api
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "auth_password_hash", "")
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    r = TestClient(app).post("/api/v1/auth/login", json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 503
