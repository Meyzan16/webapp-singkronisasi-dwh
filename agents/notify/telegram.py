"""Pengirim pesan Telegram async (dipakai notifier agent).

Kredensial dibaca dari ``ops/notify.config.json`` — file yang sama dengan
``ops/send-telegram.ps1`` (di-gitignore). Bentuk:

    { "token": "123456:ABC...", "chat_id": "12345678" }

Kalau file/kredensial tak ada, ``send_telegram`` diam-diam mengembalikan False —
notifier tak boleh menjatuhkan proses hanya karena Telegram belum di-setup.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger(__name__)

# agents/notify/telegram.py → parents[2] = repo root → ops/notify.config.json
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "ops" / "notify.config.json"

_API = "https://api.telegram.org"
_TIMEOUT = 15.0
_RETRIES = 3          # sadapan AV / DNS-belum-siap saat boot bisa gagal sesaat
_RETRY_WAIT = 5.0     # detik antar percobaan


def _load_config() -> tuple[str, str] | None:
    """Baca token + chat_id dari ops/notify.config.json. None kalau belum di-setup."""
    try:
        raw = _CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("telegram_config_invalid_json", path=str(_CONFIG_PATH))
        return None
    token = str(cfg.get("token", "")).strip()
    chat_id = str(cfg.get("chat_id", "")).strip()
    if not token or not chat_id:
        return None
    return token, chat_id


def notifier_enabled() -> bool:
    """True kalau kredensial Telegram tersedia (dipakai untuk skip loop dgn rapi)."""
    return _load_config() is not None


async def send_telegram(text: str) -> bool:
    """
    Kirim ``text`` ke chat Telegram terkonfigurasi. Return True kalau terkirim.

    Aman dipanggil kapan saja: tak pernah raise. Retry beberapa kali untuk
    menahan kegagalan sesaat (jaringan belum siap, sadapan SSL antivirus).
    """
    cfg = _load_config()
    if cfg is None:
        return False
    token, chat_id = cfg

    # DISABLE via env untuk debugging tanpa mengubah config
    if os.getenv("NOTIFY_TELEGRAM_DISABLED", "").lower() in ("1", "true", "yes"):
        return False

    url = f"{_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    last_err = ""
    for attempt in range(1, _RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            # 4xx = payload/kredensial salah → retry tak menolong, hentikan
            if 400 <= resp.status_code < 500:
                logger.warning(
                    "telegram_send_rejected",
                    status=resp.status_code,
                    body=resp.text[:200],
                )
                return False
            last_err = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001 — jaringan/SSL, coba lagi
            last_err = str(exc)[:200] or type(exc).__name__

        if attempt < _RETRIES:
            import asyncio
            await asyncio.sleep(_RETRY_WAIT)

    logger.warning("telegram_send_failed", error=last_err, attempts=_RETRIES)
    return False
