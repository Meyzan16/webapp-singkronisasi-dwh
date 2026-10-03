"""Atur login dashboard: email + password pemilik.

Jalankan SENDIRI dari repo root (password diketik tersembunyi, tak pernah dicetak):
    backend/.venv/Scripts/python.exe ops/set-password.py

Yang ditulis:
  backend/.env         AUTH_EMAIL, AUTH_PASSWORD_HASH (PBKDF2, bukan password), AUTH_SECRET
  frontend/.env.local  AUTH_SECRET (sama — proxy Next memverifikasi cookie sesi)
AUTH_SECRET baru dibuat bila belum ada; `--rotate-secret` membuat yang baru
(semua sesi yang sedang login otomatis keluar).
Setelahnya restart backend & frontend (ops/stop-night.ps1 lalu ops/start-night.ps1).
"""

from __future__ import annotations

import getpass
import os
import re
import secrets
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.services.auth import hash_password  # noqa: E402

BACKEND_ENV = os.path.join(ROOT, "backend", ".env")
FRONTEND_ENV = os.path.join(ROOT, "frontend", ".env.local")


def read_env(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def get_value(lines: list[str], key: str) -> str:
    for ln in lines:
        m = re.match(rf"^\s*{key}\s*=\s*(.*)$", ln)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return ""


def set_value(lines: list[str], key: str, value: str) -> list[str]:
    # Kutip tunggal: nilai hash memuat "$", jangan sampai diekspansi pembaca .env.
    new = f"{key}='{value}'"
    for i, ln in enumerate(lines):
        if re.match(rf"^\s*{key}\s*=", ln):
            lines[i] = new
            return lines
    return lines + [new]


def write_env(path: str, lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    rotate = "--rotate-secret" in sys.argv
    be = read_env(BACKEND_ENV)
    if not be:
        print(f"backend/.env tidak ditemukan di {BACKEND_ENV}")
        return 1

    current = get_value(be, "AUTH_EMAIL")
    email = input(f"Email login{f' [{current}]' if current else ''}: ").strip() or current
    if "@" not in email:
        print("Email tidak valid.")
        return 1
    pw = getpass.getpass("Password baru (min. 10 karakter): ")
    if len(pw) < 10:
        print("Password terlalu pendek (min. 10 karakter).")
        return 1
    if getpass.getpass("Ulangi password: ") != pw:
        print("Password tidak sama.")
        return 1

    secret = get_value(be, "AUTH_SECRET")
    if rotate or len(secret) < 32:
        secret = secrets.token_hex(32)

    be = set_value(be, "AUTH_EMAIL", email)
    be = set_value(be, "AUTH_PASSWORD_HASH", hash_password(pw))
    be = set_value(be, "AUTH_SECRET", secret)
    write_env(BACKEND_ENV, be)
    write_env(FRONTEND_ENV, set_value(read_env(FRONTEND_ENV), "AUTH_SECRET", secret))

    print("Selesai. Login disiapkan untuk", email)
    print("Restart layanan:  powershell -File ops/stop-night.ps1  lalu  powershell -File ops/start-night.ps1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
