"""Adaptive Learning untuk keputusan KELUAR — MONITOR futures DAN spot.

Sampai 1 Agu 2026 seluruh lapisan learning hanya menyetel keputusan MASUK (bobot
sinyal, veto entry). Padahal bukti menunjukkan masalah futures ada di KELUAR:
TP tersentuh 1 dari 44 trade, R:R realisasi 0,81 (menang +2,78% vs kalah −3,45%).

M7: modul ini sadar-market. Setiap fungsi menerima `market` ("futures" | "spot")
dan hanya membaca baris market itu. Sengaja SATU modul, bukan salinan untuk spot:
sisi SPOT di proyek ini berulang kali dibangun sebagai salinan lalu menyimpang
diam-diam. Satu jalur kode membuat penyimpangan mustahil terjadi tanpa terlihat.

Modul ini belajar dari `exit_events` — ledger keputusan keluar — dan
menjawab pertanyaan yang selama ini tak terjawab:
  1. Alasan close mana yang menguntungkan, mana yang merugikan?
  2. Berapa jarak TP yang REALISTIS per lane/regime (dari sebaran MFE nyata)?
  3. Apakah exit prematur — posisi ditutup sebelum harga sempat bergerak?

Semua keluarannya REKOMENDASI. Modul ini tidak pernah mengubah keputusan trading
sendiri; penerapannya lewat config di belakang flag, sama seperti lapisan
learning lain.

Satuan yang dipakai adalah kelipatan ATR, bukan persen mentah — koin ber-ATR 6%
dan 1% tak bisa dibandingkan langsung.
"""

from __future__ import annotations

import asyncio
import json
import time
from statistics import median

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_exit_event import ExitEvent
from app.models.paper_trade import PaperTrade

logger = structlog.get_logger(__name__)

#: Sampel minimum sebelum sebuah (lane) boleh menghasilkan rekomendasi.
MIN_SAMPLES_PER_LANE = 8

#: Kuantil MFE yang dipakai sebagai usulan jarak TP. 0.6 = TP yang secara historis
#: akan tersentuh ~40% posisi — sengaja tidak agresif; kuantil lebih tinggi berarti
#: TP lebih jauh dan lebih jarang kena.
TP_TARGET_QUANTILE = 0.60

#: Di bawah kelipatan ATR ini, sebuah exit dianggap "prematur" — posisi ditutup
#: padahal harga belum benar-benar bergerak ke mana pun.
PREMATURE_MFE_ATR = 0.25


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(len(ordered) * q)))
    return round(ordered[idx], 3)


# ── Backfill ──────────────────────────────────────────────────────────────────

def _reason_from_history(meta: dict, status: str, last_tick_event: str | None) -> str:
    """Alasan close terbaik yang bisa dipulihkan dari trade LAMA.

    Trade sebelum ledger ada tak menyimpan close_reason. `events[]` menyimpan
    jejak tindakan monitor, tapi event TERAKHIR belum tentu penyebab penutupan
    (mis. `time_stop_tighten` itu penyesuaian SL, bukan exit). Karena itu hasil
    tebakan diberi awalan `hist:` supaya TIDAK tercampur dengan alasan asli yang
    dicatat langsung oleh monitor — analisa bisa memisahkan keduanya.
    """
    events = meta.get("events")
    kinds = [e.get("kind") for e in events if isinstance(e, dict)] if isinstance(events, list) else []
    for kind in reversed(kinds):
        if kind in {"fail_fast", "rugpull_exit", "flash_dump_exit", "liq_guard",
                    "max_margin_loss", "emergency_close_circuit_breaker"}:
            return f"hist:{kind}"
    if last_tick_event in {"fail_fast", "liq_guard", "max_margin_loss"}:
        return f"hist:{last_tick_event}"
    return "hist:tp" if status == "tp" else "hist:sl"


#: Gaya trade (`paper_trades.style`) milik tiap market. Diturunkan dari registry
#: supaya lane futures baru ikut terbaca tanpa mengubah modul ini.
def _style_filter(market: str):
    from app.services.agent_registry import SPOT_AGENT
    if market == "spot":
        return PaperTrade.style == SPOT_AGENT
    return PaperTrade.style.like("futures%")


def _lane_for(market: str, trade, meta: dict) -> str:
    """Lane sebuah trade, dalam kosakata yang SAMA dengan monitornya.

    SPOT memakai `lane_of()` — fungsi yang sama yang dipakai monitor saat
    memutuskan — supaya nama lane di ledger, di config, dan di keputusan tak
    pernah punya tiga versi berbeda. FUTURES memakai `setup_type` yang memang
    sudah didenormalisasi ke baris trade.
    """
    if market == "spot":
        from agents.opportunity.monitor import lane_of
        return lane_of(meta, trade.alert_type)
    return trade.setup_type or meta.get("setup_type") or ""


async def backfill_exit_events(limit: int = 5000, market: str = "futures") -> dict:
    """Isi ledger dari trade yang SUDAH tertutup. Idempoten — trade yang sudah
    punya baris dilewati, jadi aman dipanggil berulang."""
    if not is_db_available():
        return {"status": "db_unavailable"}

    async with AsyncSessionLocal() as session:
        existing = {row for row in (await session.execute(
            select(ExitEvent.trade_id).where(ExitEvent.market == market))).scalars().all()}
        trades = list((await session.execute(
            select(PaperTrade).where(
                _style_filter(market),
                PaperTrade.status.in_(["tp", "sl"]),
            ).order_by(PaperTrade.closed_at).limit(limit)
        )).scalars().all())

        added = skipped = 0
        for t in trades:
            if t.id in existing:
                skipped += 1
                continue
            try:
                meta = json.loads(t.signals_json or "{}")
                if not isinstance(meta, dict):
                    meta = {}
            except (TypeError, json.JSONDecodeError):
                meta = {}

            entry = float(t.entry_price or 0.0)
            atr_pct = float(meta.get("atr_pct") or 0.0)
            if not entry:
                skipped += 1          # tanpa harga entry tak ada yang bisa dihitung
                continue

            # Tanpa ATR, kolom ber-ATR dibiarkan KOSONG — bukan diisi angka yang
            # seolah-olah sebanding. Barisnya tetap masuk karena `close_reason`,
            # P&L, dan lama tahan tetap bernilai untuk dipelajari. (Posisi SPOT
            # sebelum 2 Agu 2026 tak menyimpan ATR: analyzer menghitungnya tapi
            # nilainya dibuang saat trade dibuat.)
            def _atr(pct: float | None) -> float | None:
                return round(pct / atr_pct, 4) if (pct is not None and atr_pct) else None

            peak = meta.get("peak_pnl_pct")
            trough = meta.get("trough_pnl_pct")
            tp_dist = (abs(float(t.take_profit) - entry) / entry * 100) if t.take_profit else None
            sl_dist = (abs(entry - float(t.stop_loss)) / entry * 100) if t.stop_loss else None
            entry_at = float(t.entry_at or 0.0)
            closed_at = float(t.closed_at or entry_at)

            session.add(ExitEvent(
                market=market,
                trade_id=t.id, symbol=t.symbol, agent=t.style,
                # Lane WAJIB memakai kosakata yang sama dengan monitor, kalau
                # tidak seluruh hasil belajar menulis ke kunci config yang tak
                # pernah dibaca. Terukur 8 Agu 2026: ledger SPOT menyimpan
                # `squeeze`/`bigmover_chase` (nilai alert_type mentah) sementara
                # monitor & config memakai `accumulation`/`bigmover` — usulan TP
                # mendarat di `monitor_tp_atr_mult_lane_squeeze` yang tak ada.
                lane=_lane_for(market, t, meta),
                # SPOT selalu LONG; kolomnya tetap diisi supaya query lintas
                # market tak perlu memperlakukan spot sebagai kasus khusus.
                direction=t.direction or "LONG", regime=t.regime,
                # Alasan asli bila trade memang menyimpannya (SPOT mencatatnya
                # 100%); baru menebak dari riwayat bila tidak ada. Tebakan diberi
                # awalan `hist:` supaya tak pernah tercampur dengan yang asli.
                close_reason=(meta.get("close_reason")
                              or _reason_from_history(meta, t.status, t.last_tick_event)),
                status=t.status,
                entry_at=entry_at, closed_at=closed_at,
                held_hours=round(max(0.0, (closed_at - entry_at) / 3600.0), 3),
                pnl_pct=t.pnl_pct, pnl_dollar=t.pnl_dollar,
                atr_pct=atr_pct or None,
                mfe_atr=_atr(float(peak)) if peak is not None else None,
                mae_atr=_atr(abs(float(trough))) if trough is not None else None,
                tp_dist_atr=_atr(tp_dist), sl_dist_atr=_atr(sl_dist),
                realized_atr=_atr(t.pnl_pct),
                tp_compressed=bool(meta.get("tp_compressed")),
                trail_active=bool(t.trail_active),
                leverage=t.leverage, score=meta.get("score"),
            ))
            added += 1
        await session.commit()

    logger.info("exit_ledger_backfilled", market=market, added=added, skipped=skipped)
    return {"status": "ok", "market": market, "added": added, "skipped": skipped,
            "scanned": len(trades)}


# ── Isi mundur ATR historis (SPOT) ────────────────────────────────────────────

#: Penanda bahwa `atr_pct` sebuah trade adalah hasil REKONSTRUKSI dari klines,
#: bukan nilai yang tercatat saat posisi dibuka. Dibedakan dengan sengaja: nilai
#: rekonstruksi dihitung dari candle yang sudah selesai di sekitar waktu entry,
#: jadi ia perkiraan — bukan angka yang benar-benar dilihat scanner saat itu.
ATR_SOURCE_BACKFILL = "backfill_klines"

#: Candle 15m yang diambil sebelum entry. ATR(14) butuh 15 candle; 30 memberi
#: ruang bila ada candle yang hilang di deret Binance.
_ATR_BACKFILL_CANDLES = 30


def _atr_pct_from_klines(klines: list, entry_price: float, period: int = 14) -> float | None:
    """ATR(period) sebagai persen harga, dari deret kline mentah Binance."""
    if len(klines) < period + 1 or entry_price <= 0:
        return None
    trs = []
    for i in range(1, len(klines)):
        try:
            high, low = float(klines[i][2]), float(klines[i][3])
            prev_close = float(klines[i - 1][4])
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        except (IndexError, ValueError, TypeError):
            continue
    if len(trs) < period:
        return None
    atr = sum(trs[-period:]) / period
    return round(atr / entry_price * 100, 4) if atr > 0 else None


async def backfill_spot_atr(limit: int = 500, delay_sec: float = 0.12) -> dict:
    """Isi mundur `atr_pct` trade SPOT lama dari klines Binance.

    Latar: sampai 8 Agu 2026 scanner SPOT tak pernah menyimpan ATR, sehingga
    seluruh ledger keluar SPOT tak bisa dinormalkan terhadap volatilitas — koin
    ber-ATR 6% dan 0,1% tak bisa dibandingkan, dan mesin belajar tak punya bahan
    untuk mengusulkan jarak TP.

    Nilai yang diisi ditandai `atr_pct_source` supaya analisa bisa memisahkan
    rekonstruksi dari catatan asli. Idempoten: trade yang sudah punya `atr_pct`
    dilewati, jadi aman dipanggil berulang.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}

    import httpx
    from app.services.binance_urls import spot as _spot

    async with AsyncSessionLocal() as session:
        trades = list((await session.execute(
            select(PaperTrade).where(
                PaperTrade.style == "opportunity_spot",
                PaperTrade.status.in_(["tp", "sl"]),
            ).order_by(PaperTrade.entry_at.desc()).limit(limit)
        )).scalars().all())

        diisi = dilewati = gagal = 0
        async with httpx.AsyncClient(timeout=15) as client:
            for t in trades:
                try:
                    meta = json.loads(t.signals_json or "{}")
                    if not isinstance(meta, dict):
                        meta = {}
                except (TypeError, json.JSONDecodeError):
                    meta = {}

                if meta.get("atr_pct") or not t.entry_at or not t.entry_price:
                    dilewati += 1
                    continue

                # Candle yang BERAKHIR sebelum entry — memakai candle sesudahnya
                # berarti memakai informasi yang belum ada saat posisi dibuka.
                end_ms = int(float(t.entry_at) * 1000)
                url = _spot(f"/api/v3/klines?symbol={t.symbol}&interval=15m"
                            f"&endTime={end_ms}&limit={_ATR_BACKFILL_CANDLES}")
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        gagal += 1
                        continue
                    atr_pct = _atr_pct_from_klines(r.json(), float(t.entry_price))
                except Exception:
                    gagal += 1
                    continue

                if not atr_pct:
                    gagal += 1
                    continue

                meta["atr_pct"] = atr_pct
                meta["atr_pct_source"] = ATR_SOURCE_BACKFILL
                t.signals_json = json.dumps(meta, ensure_ascii=False)
                diisi += 1
                await asyncio.sleep(delay_sec)   # jangan menghantam rate limit

        await session.commit()

    logger.info("spot_atr_backfilled", filled=diisi, skipped=dilewati, failed=gagal)
    return {"status": "ok", "diisi": diisi, "dilewati": dilewati,
            "gagal": gagal, "dipindai": len(trades),
            "catatan": ("nilai ditandai atr_pct_source=backfill_klines — hasil "
                        "rekonstruksi dari candle sekitar entry, bukan angka yang "
                        "benar-benar tercatat saat posisi dibuka")}


# ── Analisa ───────────────────────────────────────────────────────────────────

def _bucket_stats(rows: list[ExitEvent]) -> dict:
    pnls = [r.pnl_pct for r in rows if r.pnl_pct is not None]
    mfes = [r.mfe_atr for r in rows if r.mfe_atr is not None]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    return {
        "n": len(rows),
        "expectancy_pct": round(sum(pnls) / len(pnls), 3) if pnls else None,
        "win_rate": round(100.0 * len(wins) / len(pnls), 1) if pnls else None,
        "profit_factor": round(sum(wins) / sum(losses), 3) if losses else None,
        "mfe_atr_median": round(median(mfes), 3) if mfes else None,
        "held_hours_median": round(median([r.held_hours for r in rows]), 2) if rows else None,
        # Porsi exit yang terjadi saat harga BELUM bergerak ke mana pun —
        # penanda kuat bahwa posisi ditutup terlalu dini.
        "premature_frac": (round(sum(1 for m in mfes if m < PREMATURE_MFE_ATR) / len(mfes), 3)
                           if mfes else None),
    }


async def analyze_exits(days: int = 90, market: str = "futures") -> dict:
    """Agregasi ledger keluar: per alasan close, per lane, per regime."""
    if not is_db_available():
        return {"status": "db_unavailable"}
    cutoff = time.time() - days * 86400

    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(ExitEvent).where(ExitEvent.closed_at >= cutoff,
                                    ExitEvent.market == market)
        )).scalars().all())

    if not rows:
        return {"status": "no_data", "n": 0}

    def group(key_fn) -> list[dict]:
        buckets: dict[str, list] = {}
        for r in rows:
            buckets.setdefault(key_fn(r) or "-", []).append(r)
        out = [{"key": k, **_bucket_stats(v)} for k, v in buckets.items()]
        return sorted(out, key=lambda d: -d["n"])

    return {
        "status": "ok",
        "n": len(rows),
        "window_days": days,
        "overall": _bucket_stats(rows),
        "by_close_reason": group(lambda r: r.close_reason),
        "by_lane": group(lambda r: r.lane),
        "by_regime": group(lambda r: r.regime),
    }


async def recommend_exit_params(days: int = 90, market: str = "futures") -> dict:
    """Usulan parameter keluar per lane — TP realistis + tanda exit prematur.

    Usulan TP diambil dari sebaran MFE NYATA lane tersebut, bukan angka pilihan.
    Bila mayoritas exit terjadi sebelum harga bergerak (`premature_frac` tinggi),
    memperpendek TP tak akan menolong — yang perlu ditinjau justru pemicu exit
    dini (fail-fast / time-stop / trailing). Itu dinyatakan eksplisit di `note`.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}
    cutoff = time.time() - days * 86400

    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(ExitEvent).where(ExitEvent.closed_at >= cutoff,
                                    ExitEvent.market == market)
        )).scalars().all())

    by_lane: dict[str, list] = {}
    for r in rows:
        by_lane.setdefault(r.lane or "-", []).append(r)

    recs = []
    for lane, group in sorted(by_lane.items(), key=lambda kv: -len(kv[1])):
        mfes = [r.mfe_atr for r in group if r.mfe_atr is not None]
        tps = [r.tp_dist_atr for r in group if r.tp_dist_atr is not None]
        if len(mfes) < MIN_SAMPLES_PER_LANE:
            recs.append({"lane": lane, "n": len(group), "status": "sampel_kurang",
                         "required": MIN_SAMPLES_PER_LANE})
            continue
        suggested = _quantile(mfes, TP_TARGET_QUANTILE)
        current = round(median(tps), 3) if tps else None
        premature = round(sum(1 for m in mfes if m < PREMATURE_MFE_ATR) / len(mfes), 3)
        reachable = round(100.0 * sum(1 for m in mfes if m >= (suggested or 0)) / len(mfes), 1)
        note = ("mayoritas posisi ditutup sebelum harga bergerak — tinjau pemicu "
                "exit dini (fail-fast / time-stop / trailing), memperpendek TP "
                "saja tak akan menolong"
                if premature >= 0.5 else
                "TP saat ini jauh di luar jangkauan gerak nyata lane ini"
                if (current and suggested and current > suggested * 3) else
                "TP saat ini masih dalam jangkauan wajar")
        recs.append({
            "lane": lane, "n": len(group), "status": "ok",
            "current_tp_atr": current,
            "suggested_tp_atr": suggested,
            "would_be_reached_pct": reachable,
            "mfe_atr_median": round(median(mfes), 3),
            "premature_frac": premature,
            "note": note,
        })

    return {"status": "ok", "window_days": days, "recommendations": recs,
            "target_quantile": TP_TARGET_QUANTILE,
            "premature_threshold_atr": PREMATURE_MFE_ATR}


# ── M3: apakah pemicu exit dini benar-benar mengalahkan SL? ───────────────────

#: Alasan close yang merupakan pemotongan DINI sukarela — monitor memilih keluar
#: lebih awal padahal SL belum tersentuh. Hanya alasan seperti ini yang layak
#: diadili dengan pertanyaan "apakah lebih baik daripada membiarkan SL bekerja?".
#: Prefiks `hist:` ikut dikenali supaya baris hasil backfill tak terbuang.
#:
#: Taksonominya BERBEDA per market karena monitornya memang berbeda — memaksa
#: istilah futures ke spot akan menghasilkan tabel kosong yang terbaca seolah
#: "spot tak pernah keluar dini", padahal justru mayoritas exit-nya begitu.
EARLY_EXIT_REASONS_BY_MARKET: dict[str, set[str]] = {
    "futures": {"fail_fast", "time_stop_scratch", "rugpull_exit",
                "flash_dump_exit", "flash_pump_exit"},
    # SPOT tak punya fail-fast; penutupan dininya berupa rotasi ke kandidat lain,
    # pembacaan tren berbalik, penguncian profit, dan penyesuaian risiko.
    "spot": {"urgent_rotation", "stagnant_rotation", "trend_reversal",
             "risk_adjusted", "profit_protection", "tp1_breakeven"},
}


def early_exit_reasons(market: str) -> set[str]:
    """Alasan keluar dini milik sebuah market. Market tak dikenal mengembalikan
    himpunan kosong — lebih baik tabelnya kosong dan jelas daripada mencampur
    taksonomi dua monitor yang berbeda."""
    return EARLY_EXIT_REASONS_BY_MARKET.get(market, set())

#: Sampel minimum sebelum sebuah (lane × pemicu) boleh menghasilkan usulan.
MIN_SAMPLES_PER_TRIGGER = 5

#: Batas aman: gap yang diusulkan tak boleh melampaui ini, supaya satu lane
#: bervolatilitas aneh tak menghasilkan angka yang mematikan pemicu di mana-mana.
MAX_SUGGESTED_GAP = 6.0


def _strip_hist(reason: str) -> str:
    """Buang penanda `hist:` — alasan hasil tebakan backfill tetap dianalisa,
    tapi asal-usulnya dilaporkan terpisah supaya tak dikira data langsung."""
    return reason[5:] if reason.startswith("hist:") else reason


async def analyze_exit_triggers(days: int = 90, market: str = "futures") -> dict:
    """Adili tiap pemicu exit dini per lane: menyelamatkan, atau justru merugikan?

    Ukurannya bukan untung/rugi mentah, melainkan perbandingan terhadap
    **alternatifnya**: kalau posisi dibiarkan, kerugian terburuknya adalah jarak
    SL. Pemotongan dini yang merealisasi kerugian sebesar — atau lebih besar
    dari — jarak SL berarti tidak menyelamatkan apa pun.

    `sl_gap` = jarak SL ÷ ambang pemicu. Gap kecil berarti pemicu nyaris berimpit
    dengan SL; di sana memotong dini hampir tak ada gunanya tapi membuang seluruh
    peluang harga berbalik.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}
    cutoff = time.time() - days * 86400

    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(ExitEvent).where(ExitEvent.closed_at >= cutoff,
                                    ExitEvent.market == market)
        )).scalars().all())

    dini = early_exit_reasons(market)
    buckets: dict[tuple[str, str], list] = {}
    for r in rows:
        reason = _strip_hist(r.close_reason or "")
        if reason in dini:
            buckets.setdefault((r.lane or "-", reason), []).append(r)

    out = []
    for (lane, reason), group in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        realized = [abs(r.realized_atr) for r in group
                    if r.realized_atr is not None and r.realized_atr < 0]
        sl_dists = [r.sl_dist_atr for r in group if r.sl_dist_atr]
        pnls = [r.pnl_pct for r in group if r.pnl_pct is not None]
        wins = [p for p in pnls if p > 0]
        # Gap nyata tiap trade: seberapa jauh SL dibanding titik potong.
        gaps = [round(r.sl_dist_atr / abs(r.realized_atr), 3)
                for r in group
                if r.sl_dist_atr and r.realized_atr and r.realized_atr < 0]
        # Berapa banyak yang justru merugi SEBESAR atau LEBIH dari jarak SL —
        # di situ pemotongan dini benar-benar tak menyelamatkan apa pun.
        no_saving = sum(1 for r in group
                        if r.sl_dist_atr and r.realized_atr
                        and abs(r.realized_atr) >= r.sl_dist_atr)
        out.append({
            "lane": lane, "trigger": reason, "n": len(group),
            "win_rate": round(100.0 * len(wins) / len(pnls), 1) if pnls else None,
            "expectancy_pct": round(sum(pnls) / len(pnls), 3) if pnls else None,
            "realized_atr_median": round(median(realized), 3) if realized else None,
            "sl_dist_atr_median": round(median(sl_dists), 3) if sl_dists else None,
            "sl_gap_median": round(median(gaps), 3) if gaps else None,
            "no_saving_frac": round(no_saving / len(group), 3) if group else None,
            "from_backfill": all((r.close_reason or "").startswith("hist:") for r in group),
        })

    return {"status": "ok", "window_days": days, "n": len(rows), "triggers": out,
            "min_samples": MIN_SAMPLES_PER_TRIGGER}


async def recommend_failfast_params(days: int = 90, market: str = "futures") -> dict:
    """Usulan gap fail-fast per lane, diturunkan dari ledger.

    Logikanya sederhana dan bisa diperiksa: bila di sebuah lane fail-fast belum
    pernah menang DAN sebagian besar exit-nya tak menyelamatkan apa pun, usulkan
    gap tepat di atas gap yang selama ini terjadi — sehingga pemotongan dini
    padam di lane itu, tapi tetap hidup di lane yang SL-nya memang jauh.
    """
    trig = await analyze_exit_triggers(days=days, market=market)
    if trig.get("status") != "ok":
        return trig

    recs = []
    for row in trig["triggers"]:
        if row["trigger"] != "fail_fast":
            continue
        lane, n = row["lane"], row["n"]
        if n < MIN_SAMPLES_PER_TRIGGER:
            recs.append({"lane": lane, "n": n, "status": "sampel_kurang",
                         "required": MIN_SAMPLES_PER_TRIGGER})
            continue
        merugikan = (row["win_rate"] == 0.0
                     and (row["no_saving_frac"] or 0.0) >= 0.5)
        gap_med = row["sl_gap_median"]
        if not merugikan or not gap_med:
            recs.append({"lane": lane, "n": n, "status": "biarkan",
                         "win_rate": row["win_rate"],
                         "sl_gap_median": gap_med,
                         "note": "pemicu ini belum terbukti merugikan di lane ini"})
            continue
        suggested = min(round(gap_med + 0.25, 2), MAX_SUGGESTED_GAP)
        recs.append({
            "lane": lane, "n": n, "status": "ok",
            "suggested_gap": suggested,
            "sl_gap_median": gap_med,
            "win_rate": row["win_rate"],
            "no_saving_frac": row["no_saving_frac"],
            "expectancy_pct": row["expectancy_pct"],
            "note": (f"fail-fast di lane ini menutup {n} posisi tanpa satu pun menang, "
                     f"dan {row['no_saving_frac']:.0%} di antaranya rugi sebesar atau "
                     f"lebih dari jarak SL — memotong dini tak menyelamatkan apa pun. "
                     f"Gap {suggested} memadamkannya di sini tanpa menyentuh lane lain."),
        })

    return {"status": "ok", "window_days": days, "recommendations": recs,
            "max_gap": MAX_SUGGESTED_GAP}


# ── M4: apakah lebar SL memang dirancang, atau kebetulan? ─────────────────────

#: Selisih relatif yang masih dianggap "mentok" pada batas — pembulatan harga
#: membuat perbandingan persis mustahil.
PINNED_TOLERANCE = 0.02

#: Sampel MAE minimum sebelum lebar SL boleh dinilai sama sekali.
MAE_MIN_SAMPLES = 30


def _cv(values: list[float]) -> float | None:
    """Koefisien variasi — sebaran relatif terhadap rata-rata. Dipakai untuk
    membandingkan konsistensi dua satuan yang skalanya berbeda jauh."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean == 0:
        return None
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return round(var ** 0.5 / mean, 3)


async def analyze_sl_width(days: int = 90, market: str = "futures") -> dict:
    """Bedah lebar SL per lane: dirancang terhadap volatilitas, atau terhadap harga?

    Dua pertanyaan yang dijawab di sini:

    1. **Satuan mana yang sebenarnya dipakai?** Bila sebaran SL dalam harga%
       lebih rapat daripada dalam kelipatan ATR, berarti SL disusun terhadap
       HARGA — dan perbedaan kelipatan ATR antar lane hanyalah efek samping dari
       koin yang diperdagangkan, bukan keputusan.
    2. **Berapa sering SL mentok batas?** SL yang mentok plafon berarti rumus
       sadar-volatilitas yang dimaksudkan tidak pernah benar-benar berlaku.

    Keduanya penting karena setiap gerbang yang diskalakan ke `risk_pct`
    (time-stop, fail-fast) ikut bergeser tanpa disadari.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}
    # Batas SL yang dikonfigurasi baru ada untuk FUTURES (`sl_config`). Untuk
    # market lain kolom "plafon/lantai/mentok" DIKOSONGKAN — meminjam angka
    # futures akan menghasilkan vonis "mentok plafon" yang sepenuhnya karangan.
    sl_params = None
    if market == "futures":
        from agents.futures import sl_config
        sl_params = sl_config.params

    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(ExitEvent).where(ExitEvent.closed_at >= cutoff,
                                    ExitEvent.market == market)
        )).scalars().all())

    by_lane: dict[str, list] = {}
    for r in rows:
        if r.sl_dist_atr and r.atr_pct:
            by_lane.setdefault(r.lane or "-", []).append(r)

    out, all_pct, all_atr, all_mae = [], [], [], []
    for lane, group in sorted(by_lane.items(), key=lambda kv: -len(kv[1])):
        sl_pct = [r.sl_dist_atr * r.atr_pct for r in group]     # kembali ke harga%
        sl_atr = [r.sl_dist_atr for r in group]
        mfe = [r.mfe_atr for r in group if r.mfe_atr is not None]
        mae = [r.mae_atr for r in group if r.mae_atr is not None]
        pnl = [r.pnl_pct for r in group if r.pnl_pct is not None]
        all_pct += sl_pct
        all_atr += sl_atr
        all_mae += mae

        p = sl_params(lane) if sl_params else None
        cap = p["max_pct"] if p else None
        floor = p["floor_pct"] if p else None
        pinned_max = (sum(1 for v in sl_pct if abs(v - cap) / cap <= PINNED_TOLERANCE)
                      if cap else None)
        pinned_min = (sum(1 for v in sl_pct if abs(v - floor) / floor <= PINNED_TOLERANCE)
                      if floor else None)

        out.append({
            "lane": lane, "n": len(group),
            "atr_pct_median": round(median([r.atr_pct for r in group]), 3),
            "sl_pct_median": round(median(sl_pct), 3),
            "sl_atr_median": round(median(sl_atr), 3),
            "cv_sl_pct": _cv(sl_pct),
            "cv_sl_atr": _cv(sl_atr),
            "configured_max_pct": cap,
            "configured_floor_pct": floor,
            "pinned_at_max_frac": (round(pinned_max / len(group), 3)
                                   if pinned_max is not None else None),
            "pinned_at_floor_frac": (round(pinned_min / len(group), 3)
                                     if pinned_min is not None else None),
            # SL berapa kali lebih jauh daripada gerak untung terjauh yang nyata:
            # angka besar = posisi mempertaruhkan jauh lebih banyak daripada yang
            # pernah bergerak ke arah kita.
            "sl_vs_mfe": (round(median(sl_atr) / median(mfe), 2)
                          if mfe and median(mfe) > 0 else None),
            # M4b: gerak MERUGIKAN terjauh, dan berapa PERSEN jarak SL yang
            # benar-benar terpakai. Inilah angka yang menentukan apakah SL boleh
            # dipersempit — bukan MFE. `null` = belum ada datanya.
            "mae_atr_median": round(median(mae), 3) if mae else None,
            "sl_utilization": (round(median(mae) / median(sl_atr), 3)
                               if mae and median(sl_atr) > 0 else None),
            "mae_n": len(mae),
            "win_rate": (round(100.0 * sum(1 for v in pnl if v > 0) / len(pnl), 1)
                         if pnl else None),
            "expectancy_pct": round(sum(pnl) / len(pnl), 3) if pnl else None,
        })

    cv_pct, cv_atr = _cv(all_pct), _cv(all_atr)
    verdict = None
    if cv_pct is not None and cv_atr is not None:
        verdict = ("sl_disusun_terhadap_harga" if cv_pct < cv_atr
                   else "sl_disusun_terhadap_volatilitas")

    # M4b: rekomendasi lebar SL SENGAJA tidak diterbitkan sampai MAE matang.
    # Mempersempit SL berdasarkan MFE saja adalah kekeliruan yang mahal: MFE
    # bercerita seberapa jauh harga sempat MENGUNTUNGKAN, bukan seberapa dalam ia
    # sempat MELAWAN sebelum berbalik. SL yang dipersempit tanpa melihat MAE akan
    # memotong posisi yang sebenarnya akan menang.
    mae_ready = len(all_mae) >= MAE_MIN_SAMPLES
    return {
        "status": "ok", "window_days": days, "n": len(rows),
        "lanes": out,
        "cv_sl_pct_all": cv_pct, "cv_sl_atr_all": cv_atr,
        "verdict": verdict,
        "mae_n": len(all_mae),
        "mae_required": MAE_MIN_SAMPLES,
        "sl_recommendation_ready": mae_ready,
        "sl_recommendation_note": (
            "MAE sudah cukup — lebar SL bisa dinilai terhadap seberapa dalam harga "
            "benar-benar melawan." if mae_ready else
            "Rekomendasi lebar SL BELUM diterbitkan: gerak merugikan terjauh (MAE) "
            "baru mulai direkam 2 Agu 2026. Mempersempit SL hanya berdasarkan MFE "
            "akan memotong posisi yang sebenarnya akan menang — angka utilisasi di "
            "bawah baru bermakna setelah MAE terkumpul."),
        "note": ("Sebaran yang lebih rapat menunjukkan satuan mana yang sebenarnya "
                 "mengendalikan lebar SL. Bila harga% lebih rapat daripada kelipatan "
                 "ATR, rancangan sadar-volatilitas tidak benar-benar berlaku."),
    }


# ── M8: dua parameter trailing ────────────────────────────────────────────────

#: Sampel minimum (posisi yang BENAR-BENAR menyentuh TP1) sebelum usulan trailing
#: boleh diterbitkan. Populasinya jauh lebih kecil daripada seluruh exit — hanya
#: posisi yang sampai TP1 yang pernah merasakan kedua parameter ini.
TRAIL_MIN_SAMPLES = 25

#: Perbaikan expectancy minimum (% P&L) sebelum sebuah usulan layak diajukan.
#: Di bawah ini bedanya tak bisa dipisahkan dari derau.
TRAIL_MIN_LIFT = 0.15


def _cost_pct(market: str) -> float:
    """Biaya bolak-balik — dipakai mengubah keuntungan KOTOR di TP1 jadi bersih."""
    if market == "spot":
        from app.services.trading_costs import EXECUTION_COST_PCT
        return float(EXECUTION_COST_PCT)
    from agents.futures.monitor import ROUND_TRIP
    return float(ROUND_TRIP) * 100


async def recommend_trail_params(days: int = 90, market: str = "futures") -> dict:
    """Usulkan dua parameter trailing dari perbandingan HASIL, bukan tebakan.

    Caranya: untuk tiap nilai kandidat, hitung ulang hasil tiap posisi seandainya
    nilai itu yang berlaku, lalu bandingkan expectancy-nya dengan yang nyata.

        kunci setelah TP1 (L') : bila harga pernah turun di bawah L', posisi
                                 berhenti di sana → hasil = L' × keuntungan TP1
        maju ke TP1 (A')       : bila kemajuan pernah mencapai A' DAN harga
                                 pernah balik ke bawah TP1, posisi berhenti di
                                 TP1 → hasil = keuntungan TP1

    **Batas yang jujur — data ini TERSENSOR, dan arahnya berlawanan.** Nilai yang
    berlaku memotong posisi begitu tersentuh, jadi ada wilayah yang tak pernah
    teramati. Untuk KUNCI, wilayah gelap itu ada di bawah → hanya menaikkan yang
    bisa dinilai. Untuk MAJU, wilayah gelapnya ada di atas → hanya menurunkan
    yang bisa dinilai. Kandidat di sisi gelap sengaja tak dievaluasi, bukan
    dievaluasi lalu ditolak.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}

    cfg = _trail_config(market)
    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(ExitEvent).where(ExitEvent.closed_at >= cutoff,
                                    ExitEvent.market == market)
        )).scalars().all())

    # Hanya posisi yang menyentuh TP1 — di posisi lain kedua parameter ini tak
    # pernah berlaku, jadi memasukkannya hanya mengencerkan bukti.
    pop = [r for r in rows
           if r.retrace_after_tp1_frac is not None
           and r.tp1_gain_pct and r.pnl_pct is not None]
    cost = _cost_pct(market)
    n = len(pop)
    ready = n >= TRAIL_MIN_SAMPLES

    def _expectancy(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    actual = _expectancy([r.pnl_pct for r in pop]) if pop else None

    lock_now = cfg["lock"]
    adv_now = cfg["advance"]
    lock_grid = [round(lock_now + i * 0.05, 2) for i in range(0, 6)
                 if lock_now + i * 0.05 <= 1.0]
    # Arah kandidat BERBEDA untuk dua parameter ini, dan bukan karena selera:
    #
    #   kunci (L)  = level STOP. Apa yang terjadi di bawah L tak pernah teramati
    #                karena posisi sudah dipotong di sana → hanya NAIK yang bisa
    #                dinilai.
    #   maju (A)   = PEMICU pada kemajuan naik, yang hasilnya memasang lantai di
    #                TP1. Posisi yang belum mencapai A tetap terlihat apa adanya
    #                → menurunkan A bisa dinilai. Menaikkannya TIDAK: posisi yang
    #                sudah terlanjur dilantai TP1 menyembunyikan apa yang akan
    #                terjadi di bawah TP1.
    adv_grid = [round(adv_now - i * 0.10, 2) for i in range(0, 6)
                if adv_now - i * 0.10 >= 0.0]

    def _pilih(curve: list[dict], sekarang: float) -> dict:
        if not cfg.get("applicable"):
            return {"recommended": None, "lift_pct": None,
                    "reason": cfg.get("why", "tak_bisa_diterapkan")}
        if not ready or not curve:
            return {"recommended": None, "lift_pct": None,
                    "reason": "sampel_belum_cukup"}
        dasar = next((c["expectancy_pct"] for c in curve if c["value"] == sekarang),
                     actual or 0.0)
        terbaik = max(curve, key=lambda c: c["expectancy_pct"])
        lift = round(terbaik["expectancy_pct"] - dasar, 4)
        if terbaik["value"] == sekarang or lift < TRAIL_MIN_LIFT:
            return {"recommended": None, "lift_pct": lift,
                    "reason": "tak_ada_kandidat_cukup_baik"}
        return {"recommended": terbaik["value"], "lift_pct": lift}

    lock_curve = lock_curve_for(pop, lock_grid, cost)
    adv_curve = adv_curve_for(pop, adv_grid, cost)
    return {
        "status": "ok", "market": market, "window_days": days,
        "n_exit": len(rows), "n_sampai_tp1": n,
        "required": TRAIL_MIN_SAMPLES,
        "recommendation_ready": ready,
        "expectancy_actual_pct": actual,
        "cost_pct": round(cost, 3),
        "params": {
            "trail_lock_after_tp1": {
                "current": lock_now, "curve": lock_curve, **_pilih(lock_curve, lock_now)},
            "trail_advance_tp1_tp2": {
                "current": adv_now, "curve": adv_curve, **_pilih(adv_curve, adv_now)},
        },
        "note": (
            "Bukti mulai direkam 10 Agu 2026; baris ledger sebelumnya TIDAK bisa "
            "dipakai karena gerak sesudah TP1 tak pernah disimpan dan mustahil "
            "direkonstruksi. Arah kandidat berbeda per parameter: kunci hanya "
            "dinilai NAIK, maju hanya dinilai TURUN — sisi lainnya tersensor "
            "oleh nilai yang berlaku sekarang."),
    }


def _expectancy_of(vals: list[float]) -> float:
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def lock_curve_for(pop: list, grid: list[float], cost: float) -> list[dict]:
    """Hasil rata-rata seandainya kunci-setelah-TP1 bernilai tiap kandidat.

    Aturannya satu kalimat: bila harga pernah turun DI BAWAH kandidat, posisi
    berhenti di sana (hasil = kandidat × keuntungan TP1, dikurangi biaya);
    selain itu hasilnya tetap seperti yang nyata terjadi.
    """
    out = []
    for cand in grid:
        hasil = [(cand * r.tp1_gain_pct - cost) if r.retrace_after_tp1_frac < cand
                 else r.pnl_pct for r in pop]
        out.append({"value": cand, "expectancy_pct": _expectancy_of(hasil),
                    "n_terpengaruh": sum(1 for r in pop
                                         if r.retrace_after_tp1_frac < cand)})
    return out


def adv_curve_for(pop: list, grid: list[float], cost: float) -> list[dict]:
    """Hasil rata-rata seandainya pemicu maju-ke-TP1 bernilai tiap kandidat.

    SL baru pindah ke TP1 kalau kemajuan pernah mencapai kandidat. Setelah itu
    ia hanya menggigit bila harga memang pernah balik ke bawah TP1 — karena itu
    syaratnya DUA-DUANYA, bukan salah satu. Tanpa syarat kedua, tiap kandidat
    rendah akan terlihat menang secara palsu.
    """
    out = []
    sub = [r for r in pop if r.ext_after_tp1_frac is not None]
    for cand in grid:
        hasil, terpengaruh = [], 0
        for r in sub:
            if r.ext_after_tp1_frac >= cand and r.retrace_after_tp1_frac < 1.0:
                terpengaruh += 1
                hasil.append(r.tp1_gain_pct - cost)
            else:
                hasil.append(r.pnl_pct)
        out.append({"value": cand, "expectancy_pct": _expectancy_of(hasil),
                    "n_terpengaruh": terpengaruh, "n": len(sub)})
    return out


def _trail_config(market: str) -> dict:
    """Nilai trailing yang BERLAKU sekarang, dibaca dari config monitor terkait —
    bukan disalin, supaya usulan selalu dibandingkan terhadap yang nyata."""
    if market == "spot":
        from agents.opportunity import monitor_config as scfg
        return {"lock": scfg.TRAIL_LOCK_AFTER_TP1_FRAC,
                "advance": scfg.TRAIL_ADVANCE_TP1_TP2_FRAC, "applicable": True}
    from agents.futures import monitor_config as mcfg
    return {"lock": mcfg.TRAIL_LOCK_AFTER_TP1_FRAC,
            "advance": mcfg.TRAIL_ADVANCE_TP1_TP2_FRAC, "applicable": True}


# ── Penerapan ─────────────────────────────────────────────────────────────────

async def apply_exit_recommendations(days: int = 90, dry_run: bool = True,
                                     market: str = "futures") -> dict:
    """Tulis usulan batas TP per lane ke `agent_config` (PRIORITAS 2).

    Ini satu-satunya jalan hasil belajar EXIT menyentuh keputusan monitor, dan
    jalannya sengaja berlapis:

    1. `dry_run=True` (default) — tidak menulis apa pun, hanya melaporkan apa
       yang AKAN ditulis.
    2. Menulis pun belum mengubah perilaku: monitor mengabaikan angka per-lane
       selama `<market>.monitor_exit_learning_enabled` masih 0 — saklarnya
       TERPISAH per market sejak MONITOR SPOT ikut tersambung.
    3. Lane dengan sampel kurang dari `MIN_SAMPLES_PER_LANE` DILEWATI — lebih
       baik lane itu tetap pakai batas global daripada ditala oleh 2 trade.
    4. Lane yang mayoritas exit-nya prematur juga DILEWATI: di sana harga belum
       sempat bergerak, jadi memperpendek TP menyembuhkan gejala yang salah.

    Lapisan ini menjaga sifat yang sama dengan learning sisi masuk — mesin boleh
    mengusulkan, penyalaan tetap keputusan pemilik.
    """
    from app.models.agent_config import AgentConfig
    from agents.futures.monitor_config import tp_lane_key, failfast_gap_key

    reco = await recommend_exit_params(days=days, market=market)
    if reco.get("status") != "ok":
        return reco

    planned, skipped = [], []

    # M3 — gap fail-fast per lane. Dipasang lewat jalur yang sama supaya satu
    # tombol menerapkan seluruh hasil belajar sisi keluar, bukan tersebar.
    ff = await recommend_failfast_params(days=days, market=market)
    for rec in ff.get("recommendations", []):
        lane = rec["lane"]
        if rec.get("status") != "ok":
            skipped.append({"lane": lane, "target": "failfast_gap",
                            "reason": rec.get("status"), "n": rec.get("n")})
            continue
        planned.append({"lane": lane, "key": failfast_gap_key(lane),
                        "value": rec["suggested_gap"], "target": "failfast_gap",
                        "n": rec["n"], "note": rec["note"]})

    for rec in reco["recommendations"]:
        lane = rec["lane"]
        if rec.get("status") != "ok":
            skipped.append({"lane": lane, "target": "tp_atr",
                            "reason": "sampel_kurang", "n": rec.get("n")})
            continue
        if rec.get("premature_frac", 0.0) >= 0.5:
            skipped.append({"lane": lane, "target": "tp_atr",
                            "reason": "mayoritas_exit_prematur",
                            "premature_frac": rec["premature_frac"]})
            continue
        if not rec.get("suggested_tp_atr"):
            skipped.append({"lane": lane, "target": "tp_atr", "reason": "usulan_kosong"})
            continue
        planned.append({"lane": lane, "key": tp_lane_key(lane), "target": "tp_atr",
                        "value": rec["suggested_tp_atr"],
                        "current_tp_atr": rec.get("current_tp_atr"),
                        "would_be_reached_pct": rec.get("would_be_reached_pct"),
                        "n": rec["n"]})

    if dry_run or not planned:
        return {"status": "dry_run" if dry_run else "no_change",
                "planned": planned, "skipped": skipped, "written": 0}

    written = 0
    async with AsyncSessionLocal() as session:
        for item in planned:
            row = (await session.execute(select(AgentConfig).where(
                AgentConfig.agent_group == "futures",
                AgentConfig.key == item["key"],
            ))).scalar_one_or_none()
            if row is None:
                session.add(AgentConfig(
                    agent_group="futures", key=item["key"],
                    value_num=item["value"], default_num=0.0,
                    description=(f"Lane {item['lane']}: {item['target']} hasil belajar "
                                 f"dari {item['n']} exit nyata. 0 = pakai nilai global."),
                    category="monitor", updated_by="exit_learning",
                ))
            else:
                row.value_num = item["value"]
                row.updated_at = time.time()
                row.updated_by = "exit_learning"
            written += 1
        await session.commit()

    logger.info("exit_recommendations_applied", written=written,
                skipped=len(skipped))
    return {"status": "ok", "planned": planned, "skipped": skipped,
            "written": written,
            "note": (f"angka tersimpan tapi BELUM berpengaruh — nyalakan "
                     f"{market}.monitor_exit_learning_enabled untuk memakainya")}
