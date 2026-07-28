"""Telegram notification agent.

Zero-touch terhadap logika trading: hanya MEMBACA tabel `paper_trades` untuk
mendeteksi posisi baru dibuka / ditutup, lalu mengirim ringkasan ke Telegram.
Kredensial dibaca dari `ops/notify.config.json` (di-gitignore).
"""

from agents.notify.telegram import send_telegram
from agents.notify.trade_watcher import run_notifier_loop

__all__ = ["send_telegram", "run_notifier_loop"]
