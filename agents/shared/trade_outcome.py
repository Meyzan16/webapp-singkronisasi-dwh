"""Satu definisi "menang" untuk seluruh proyek.

Berkas ini sudah dua kali jadi pusat kerusakan yang mahal. Riwayatnya penting,
jadi disimpan lengkap.

── Bab 1 (10 Agu 2026): kemenangan yang terbaca kalah ────────────────────────
    FUTURES: 21 trade untung, **20 di antaranya dilabeli KALAH**.
Penyebabnya satu baris yang diulang di 15+ tempat:
    is_win = t.status == "tp" and t.pnl_pct > 0        # SALAH
`status` menyimpan MEKANISME yang menutup posisi, bukan hasilnya. Trailing stop
yang bergerak di atas entry menutup dengan `status="sl"` walau membukukan untung
— itulah `sl_plus`. Akibatnya `risk_gate` melihat lane `bigmover` ber-WR 4%
(sebenarnya 64%) lalu menjedanya, dan `weight_updater` melatih SETIAP bobot
sinyal futures dari label terbalik.

── Bab 2 (5 Sep 2026): impas yang terbaca menang ─────────────────────────────
Perbaikan Bab 1 — `pnl_pct > 0` — benar arahnya tapi terlalu longgar, dan
kelonggaran itu punya harga yang terukur:

    "menang" menurut definisi lama : 55 dari 110  → WR 50,0%
    di antaranya membukukan < $0,50: 38 (69%)
    WR yang benar-benar bermakna (≥ $1) : 10,9%
    WR ≥ $3                            :  6,4%

Trade yang ditutup di +$0,30 bukan kemenangan — itu biaya fee yang kebetulan
tertutup. Tapi ketiga pengambil keputusan memakannya sebagai sukses:
  * `weight_updater` melatih tiap bobot sinyal dengan label ini, sehingga sinyal
    yang menghasilkan +$0,30 dihargai setara dengan yang +$14;
  * `risk_gate` menilai jeda lane dari WR 50% yang fiktif;
  * seluruh laporan WR di UI ikut fiktif.

Inilah sebab paling masuk akal kenapa engine belajar tak pernah mengalahkan
baseline: ia diajari bahwa impas itu sukses.

Karena itu FUTURES kini menuntut kemenangan **membukukan untung yang bermakna**:
lebih besar dari ambang dolar DAN dari kelipatan biaya trade itu sendiri. Trade
di antara dua ambang bukan menang, bukan pula kalah — ia `is_scratch`, dan
pemanggil yang melatih model wajib membuangnya, bukan menghitungnya sebagai
kekalahan (menghukum sinyal karena menghasilkan +$0,30 sama menyesatkannya
dengan memujinya).

SPOT SENGAJA TIDAK BERUBAH. Monitornya menandai exit untung sebagai `status="tp"`
dan tak punya masalah sl_plus; mengubah ambangnya berarti mengubah engine spot
yang tak boleh disentuh. Market diturunkan dari `trade.style`, bukan dari
parameter — supaya tak ada satu pun dari 10 pemanggil yang bisa lupa mengirimnya
dan diam-diam memakai aturan market yang salah.
"""

from __future__ import annotations

import json

import structlog

logger = structlog.get_logger(__name__)


# ── Ambang "menang" FUTURES ───────────────────────────────────────────────────
# Nilai BEKU = cadangan saat DB tak terbaca; nilai hidup datang dari
# `agent_config` lewat refresh(). Keputusan owner 5 Sep 2026 (K6): $3.
_FROZEN: dict[str, float] = {
    # Untung bersih minimum ($) agar sebuah trade disebut menang.
    "win_min_profit_usd": 3.0,
    # …DAN minimal sekian kali biaya round-trip trade itu sendiri. Dua syarat,
    # bukan satu: $3 pada posisi $100 itu kemenangan nyata, tapi $3 pada posisi
    # $3.000 masih di dalam derau biaya.
    "win_min_cost_mult": 2.0,
}
_LIVE: dict[str, float] = dict(_FROZEN)

# Fee round-trip futures (%) — cadangan saat trade tak menyimpan cost_floor_pct.
_FALLBACK_COST_PCT = 0.10


def refresh_from_config(values: dict[str, float]) -> None:
    """Pasang nilai hidup. Dipanggil `weight_updater`/`risk_gate` sekali per
    siklus; dipisah dari pembacaan config supaya modul ini tetap murni dan
    gampang diuji."""
    for key in _FROZEN:
        if key in values:
            _LIVE[key] = float(values[key])


def thresholds() -> dict[str, float]:
    """Ambang yang sedang berlaku — untuk diagnostik & UI."""
    return dict(_LIVE)


def is_futures(trade) -> bool:
    return str(getattr(trade, "style", "") or "").startswith("futures")


def trade_cost_usd(trade) -> float:
    """Biaya round-trip trade ini dalam dolar.

    Dibaca dari `cost_floor_pct` yang disimpan auto_trader saat membuka (fee +
    2× slippage + estimasi funding). Baris lama tanpa itu memakai fee saja —
    lebih kecil dari biaya sebenarnya, jadi ambangnya lebih longgar, bukan lebih
    ketat: sebuah kesalahan tak boleh membuat trade lama tampak lebih buruk dari
    kenyataannya.
    """
    notional = float(getattr(trade, "position_size", 0.0) or 0.0)
    if notional <= 0:
        return 0.0
    cost_pct = _FALLBACK_COST_PCT
    try:
        meta = json.loads(getattr(trade, "signals_json", None) or "{}") or {}
        raw = meta.get("cost_floor_pct")
        if isinstance(raw, (int, float)) and raw > 0:
            cost_pct = float(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return notional * cost_pct / 100.0


def win_threshold_usd(trade) -> float:
    """Berapa dolar yang harus dibukukan trade INI agar disebut menang."""
    return max(_LIVE["win_min_profit_usd"],
               _LIVE["win_min_cost_mult"] * trade_cost_usd(trade))


def realized_usd(trade) -> float:
    """P&L dolar yang tersimpan; baris lama tanpa itu diturunkan dari notional."""
    val = getattr(trade, "pnl_dollar", None)
    if val is not None:
        return float(val)
    notional = float(getattr(trade, "position_size", 0.0) or 0.0)
    return (float(getattr(trade, "pnl_pct", 0.0) or 0.0) / 100.0) * notional


def is_win(trade) -> bool:
    """Menang = membukukan untung yang BERMAKNA (futures) / untung (spot).

    Sengaja TIDAK melihat `status`: mekanisme penutup (tp / sl / trailing) tak
    menentukan apakah sebuah trade menguntungkan — pelajaran Bab 1 di atas.
    """
    if not is_futures(trade):
        return (getattr(trade, "pnl_pct", 0.0) or 0.0) > 0        # SPOT: tak berubah
    return realized_usd(trade) >= win_threshold_usd(trade)


def is_loss(trade) -> bool:
    """Kalah = rugi yang bermakna. Cermin `is_win`, bukan sekadar `not is_win`:
    di antara keduanya ada wilayah impas yang bukan dua-duanya."""
    if not is_futures(trade):
        return (getattr(trade, "pnl_pct", 0.0) or 0.0) <= 0
    return realized_usd(trade) <= -win_threshold_usd(trade)


def is_scratch(trade) -> bool:
    """Impas — hasilnya di dalam derau biaya, jadi tak mengajarkan apa pun.

    Pemanggil yang MELATIH (weight_updater) atau MENGHUKUM (risk_gate) wajib
    membuang trade ini. Menghitungnya sebagai kekalahan akan menghukum sinyal
    yang sebenarnya netral; menghitungnya sebagai kemenangan adalah bug yang
    justru sedang diperbaiki di sini.
    """
    if not is_futures(trade):
        return False        # SPOT tak punya konsep ini
    return not is_win(trade) and not is_loss(trade)


def is_closed(trade) -> bool:
    """Sudah selesai — hanya trade selesai yang boleh masuk hitungan hasil."""
    return getattr(trade, "status", None) in ("tp", "sl")


def is_decisive(trade) -> bool:
    """Selesai DAN hasilnya cukup tegas untuk dipelajari."""
    return is_closed(trade) and not is_scratch(trade)


def win_loss(trades) -> tuple[int, int]:
    """`(menang, total)` atas trade yang selesai DAN tegas.

    `total` sengaja tidak memuat trade impas: memasukkannya membuat win-rate
    turun hanya karena banyak trade berakhir netral, padahal yang ingin diukur
    adalah "kalau tesisnya terbukti, seberapa sering ia benar".
    """
    tegas = [t for t in trades if is_decisive(t)]
    return sum(1 for t in tegas if is_win(t)), len(tegas)


def summarize(trades) -> dict:
    """Ringkasan tiga-arah untuk UI/laporan — menang / kalah / impas."""
    selesai = [t for t in trades if is_closed(t)]
    menang = sum(1 for t in selesai if is_win(t))
    impas = sum(1 for t in selesai if is_scratch(t))
    return {
        "menang": menang,
        "kalah": len(selesai) - menang - impas,
        "impas": impas,
        "selesai": len(selesai),
        "win_rate": round(menang / (len(selesai) - impas) * 100, 1) if len(selesai) - impas else 0.0,
    }
