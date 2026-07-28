"""Encrypted secret store using Windows DPAPI (CryptProtectData).

Kunci Binance disimpan terenkripsi di backend/.secrets/binance.json dan hanya bisa
didekripsi oleh akun Windows yang sama di mesin yang sama (DPAPI user scope).
Tidak menambah dependensi (pakai ctypes -> crypt32.dll). No-op di non-Windows
(mis. container Linux) sehingga fallback .env tetap jalan di sana.

Setup sekali (dari folder backend/, venv aktif):
    python -m app.services.secret_store encrypt-from-env
lalu kosongkan BINANCE_API_KEY/SECRET di .env.
"""

from __future__ import annotations

import base64
import json
import os
import sys

_IS_WIN = sys.platform == "win32"

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SECRETS_DIR = os.path.join(_BACKEND_DIR, ".secrets")
_SECRETS_FILE = os.path.join(_SECRETS_DIR, "binance.json")


if _IS_WIN:
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _protect(data: bytes) -> bytes:
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        # CRYPTPROTECT_LOCAL_MACHINE not set -> user-scoped (hanya akun ini)
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def _unprotect(data: bytes) -> bytes:
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def save_binance_secrets(api_key: str, api_secret: str) -> str:
    """Encrypt + tulis ke store. Return path file. Windows only."""
    if not _IS_WIN:
        raise RuntimeError("DPAPI hanya tersedia di Windows")
    os.makedirs(_SECRETS_DIR, exist_ok=True)
    payload = {
        "api_key": base64.b64encode(_protect(api_key.encode("utf-8"))).decode("ascii"),
        "api_secret": base64.b64encode(_protect(api_secret.encode("utf-8"))).decode("ascii"),
    }
    with open(_SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return _SECRETS_FILE


def load_binance_secrets() -> tuple[str, str] | None:
    """Return (api_key, api_secret) terdekripsi, atau None kalau tak ada/gagal/non-Windows."""
    if not _IS_WIN or not os.path.exists(_SECRETS_FILE):
        return None
    try:
        with open(_SECRETS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        key = _unprotect(base64.b64decode(d["api_key"])).decode("utf-8")
        secret = _unprotect(base64.b64decode(d["api_secret"])).decode("utf-8")
        if key and secret:
            return key, secret
    except Exception:
        return None
    return None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "encrypt-from-env":
        # Baca plaintext yang MASIH ada di .env, enkripsi, simpan.
        from app.config import Settings
        s = Settings()
        if not s.binance_api_key or not s.binance_api_secret:
            print("GAGAL: BINANCE_API_KEY/SECRET kosong di .env - tidak ada yang dienkripsi")
            sys.exit(1)
        path = save_binance_secrets(s.binance_api_key, s.binance_api_secret)
        # Verifikasi round-trip
        chk = load_binance_secrets()
        ok = chk == (s.binance_api_key, s.binance_api_secret)
        print(f"OK tersimpan terenkripsi -> {path}")
        print(f"verifikasi dekripsi: {'COCOK' if ok else 'GAGAL'}")
        sys.exit(0 if ok else 2)
    elif cmd == "encrypt-input":
        # Rotate: masukkan kunci BARU lewat input tersembunyi (tak menyentuh .env/disk plaintext).
        import getpass
        key = getpass.getpass("Paste API KEY (tak tampil): ").strip()
        secret = getpass.getpass("Paste API SECRET (tak tampil): ").strip()
        if not key or not secret:
            print("GAGAL: key/secret kosong")
            sys.exit(1)
        path = save_binance_secrets(key, secret)
        chk = load_binance_secrets()
        ok = chk == (key, secret)
        print(f"OK tersimpan terenkripsi -> {path}")
        print(f"verifikasi dekripsi: {'COCOK' if ok else 'GAGAL'}")
        sys.exit(0 if ok else 2)
    elif cmd == "check":
        chk = load_binance_secrets()
        print(f"store ada & bisa didekripsi: {bool(chk)}")
        if chk:
            print(f"api_key prefix: {chk[0][:8]}...")
    else:
        print("usage: python -m app.services.secret_store [encrypt-from-env|check]")
