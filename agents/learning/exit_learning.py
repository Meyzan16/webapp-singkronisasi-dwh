"""Adaptive Learning untuk keputusan KELUAR — khusus MONITOR futures.

Sampai 1 Agu 2026 seluruh lapisan learning hanya menyetel keputusan MASUK (bobot
sinyal, veto entry). Padahal bukti menunjukkan masalah futures ada di KELUAR:
TP tersentuh 1 dari 44 trade, R:R realisasi 0,81 (menang +2,78% vs kalah −3,45%).

Modul ini belajar dari `futures_exit_events` — ledger keputusan keluar — dan
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

import json
import time
from statistics import median

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.futures_exit_event import FuturesExitEvent
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


async def backfill_exit_events(limit: int = 5000) -> dict:
    """Isi ledger dari trade futures yang SUDAH tertutup. Idempoten — trade yang
    sudah punya baris dilewati, jadi aman dipanggil berulang."""
    if not is_db_available():
        return {"status": "db_unavailable"}

    async with AsyncSessionLocal() as session:
        existing = {row for row in (await session.execute(
            select(FuturesExitEvent.trade_id))).scalars().all()}
        trades = list((await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.like("futures%"),
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
            if not entry or not atr_pct:
                skipped += 1          # tanpa ATR baris tak bisa dinormalkan
                continue

            def _atr(pct: float | None) -> float | None:
                return round(pct / atr_pct, 4) if (pct is not None and atr_pct) else None

            peak = meta.get("peak_pnl_pct")
            tp_dist = (abs(float(t.take_profit) - entry) / entry * 100) if t.take_profit else None
            sl_dist = (abs(entry - float(t.stop_loss)) / entry * 100) if t.stop_loss else None
            entry_at = float(t.entry_at or 0.0)
            closed_at = float(t.closed_at or entry_at)

            session.add(FuturesExitEvent(
                trade_id=t.id, symbol=t.symbol, agent=t.style,
                lane=t.setup_type or meta.get("setup_type") or "",
                direction=t.direction, regime=t.regime,
                close_reason=_reason_from_history(meta, t.status, t.last_tick_event),
                status=t.status,
                entry_at=entry_at, closed_at=closed_at,
                held_hours=round(max(0.0, (closed_at - entry_at) / 3600.0), 3),
                pnl_pct=t.pnl_pct, pnl_dollar=t.pnl_dollar,
                atr_pct=atr_pct,
                mfe_atr=_atr(float(peak)) if peak is not None else None,
                tp_dist_atr=_atr(tp_dist), sl_dist_atr=_atr(sl_dist),
                realized_atr=_atr(t.pnl_pct),
                tp_compressed=bool(meta.get("tp_compressed")),
                trail_active=bool(t.trail_active),
                leverage=t.leverage, score=meta.get("score"),
            ))
            added += 1
        await session.commit()

    logger.info("exit_ledger_backfilled", added=added, skipped=skipped)
    return {"status": "ok", "added": added, "skipped": skipped, "scanned": len(trades)}


# ── Analisa ───────────────────────────────────────────────────────────────────

def _bucket_stats(rows: list[FuturesExitEvent]) -> dict:
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


async def analyze_exits(days: int = 90) -> dict:
    """Agregasi ledger keluar: per alasan close, per lane, per regime."""
    if not is_db_available():
        return {"status": "db_unavailable"}
    cutoff = time.time() - days * 86400

    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(FuturesExitEvent).where(FuturesExitEvent.closed_at >= cutoff)
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


async def recommend_exit_params(days: int = 90) -> dict:
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
            select(FuturesExitEvent).where(FuturesExitEvent.closed_at >= cutoff)
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
EARLY_EXIT_REASONS = {"fail_fast", "time_stop_scratch", "rugpull_exit",
                      "flash_dump_exit", "flash_pump_exit"}

#: Sampel minimum sebelum sebuah (lane × pemicu) boleh menghasilkan usulan.
MIN_SAMPLES_PER_TRIGGER = 5

#: Batas aman: gap yang diusulkan tak boleh melampaui ini, supaya satu lane
#: bervolatilitas aneh tak menghasilkan angka yang mematikan pemicu di mana-mana.
MAX_SUGGESTED_GAP = 6.0


def _strip_hist(reason: str) -> str:
    """Buang penanda `hist:` — alasan hasil tebakan backfill tetap dianalisa,
    tapi asal-usulnya dilaporkan terpisah supaya tak dikira data langsung."""
    return reason[5:] if reason.startswith("hist:") else reason


async def analyze_exit_triggers(days: int = 90) -> dict:
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
            select(FuturesExitEvent).where(FuturesExitEvent.closed_at >= cutoff)
        )).scalars().all())

    buckets: dict[tuple[str, str], list] = {}
    for r in rows:
        reason = _strip_hist(r.close_reason or "")
        if reason in EARLY_EXIT_REASONS:
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


async def recommend_failfast_params(days: int = 90) -> dict:
    """Usulan gap fail-fast per lane, diturunkan dari ledger.

    Logikanya sederhana dan bisa diperiksa: bila di sebuah lane fail-fast belum
    pernah menang DAN sebagian besar exit-nya tak menyelamatkan apa pun, usulkan
    gap tepat di atas gap yang selama ini terjadi — sehingga pemotongan dini
    padam di lane itu, tapi tetap hidup di lane yang SL-nya memang jauh.
    """
    trig = await analyze_exit_triggers(days=days)
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


async def analyze_sl_width(days: int = 90) -> dict:
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
    from agents.futures import sl_config

    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(FuturesExitEvent).where(FuturesExitEvent.closed_at >= cutoff)
        )).scalars().all())

    by_lane: dict[str, list] = {}
    for r in rows:
        if r.sl_dist_atr and r.atr_pct:
            by_lane.setdefault(r.lane or "-", []).append(r)

    out, all_pct, all_atr = [], [], []
    for lane, group in sorted(by_lane.items(), key=lambda kv: -len(kv[1])):
        sl_pct = [r.sl_dist_atr * r.atr_pct for r in group]     # kembali ke harga%
        sl_atr = [r.sl_dist_atr for r in group]
        mfe = [r.mfe_atr for r in group if r.mfe_atr is not None]
        pnl = [r.pnl_pct for r in group if r.pnl_pct is not None]
        all_pct += sl_pct
        all_atr += sl_atr

        p = sl_config.params(lane)
        cap, floor = p["max_pct"], p["floor_pct"]
        pinned_max = sum(1 for v in sl_pct if cap > 0 and abs(v - cap) / cap <= PINNED_TOLERANCE)
        pinned_min = sum(1 for v in sl_pct if floor > 0 and abs(v - floor) / floor <= PINNED_TOLERANCE)

        out.append({
            "lane": lane, "n": len(group),
            "atr_pct_median": round(median([r.atr_pct for r in group]), 3),
            "sl_pct_median": round(median(sl_pct), 3),
            "sl_atr_median": round(median(sl_atr), 3),
            "cv_sl_pct": _cv(sl_pct),
            "cv_sl_atr": _cv(sl_atr),
            "configured_max_pct": cap,
            "configured_floor_pct": floor,
            "pinned_at_max_frac": round(pinned_max / len(group), 3),
            "pinned_at_floor_frac": round(pinned_min / len(group), 3),
            # SL berapa kali lebih jauh daripada gerak untung terjauh yang nyata:
            # angka besar = posisi mempertaruhkan jauh lebih banyak daripada yang
            # pernah bergerak ke arah kita.
            "sl_vs_mfe": (round(median(sl_atr) / median(mfe), 2)
                          if mfe and median(mfe) > 0 else None),
            "win_rate": (round(100.0 * sum(1 for v in pnl if v > 0) / len(pnl), 1)
                         if pnl else None),
            "expectancy_pct": round(sum(pnl) / len(pnl), 3) if pnl else None,
        })

    cv_pct, cv_atr = _cv(all_pct), _cv(all_atr)
    verdict = None
    if cv_pct is not None and cv_atr is not None:
        verdict = ("sl_disusun_terhadap_harga" if cv_pct < cv_atr
                   else "sl_disusun_terhadap_volatilitas")

    return {
        "status": "ok", "window_days": days, "n": len(rows),
        "lanes": out,
        "cv_sl_pct_all": cv_pct, "cv_sl_atr_all": cv_atr,
        "verdict": verdict,
        "note": ("Sebaran yang lebih rapat menunjukkan satuan mana yang sebenarnya "
                 "mengendalikan lebar SL. Bila harga% lebih rapat daripada kelipatan "
                 "ATR, rancangan sadar-volatilitas tidak benar-benar berlaku."),
    }


# ── Penerapan ─────────────────────────────────────────────────────────────────

async def apply_exit_recommendations(days: int = 90, dry_run: bool = True) -> dict:
    """Tulis usulan batas TP per lane ke `agent_config` (PRIORITAS 2).

    Ini satu-satunya jalan hasil belajar EXIT menyentuh keputusan monitor, dan
    jalannya sengaja berlapis:

    1. `dry_run=True` (default) — tidak menulis apa pun, hanya melaporkan apa
       yang AKAN ditulis.
    2. Menulis pun belum mengubah perilaku: monitor mengabaikan angka per-lane
       selama `futures.monitor_exit_learning_enabled` masih 0.
    3. Lane dengan sampel kurang dari `MIN_SAMPLES_PER_LANE` DILEWATI — lebih
       baik lane itu tetap pakai batas global daripada ditala oleh 2 trade.
    4. Lane yang mayoritas exit-nya prematur juga DILEWATI: di sana harga belum
       sempat bergerak, jadi memperpendek TP menyembuhkan gejala yang salah.

    Lapisan ini menjaga sifat yang sama dengan learning sisi masuk — mesin boleh
    mengusulkan, penyalaan tetap keputusan pemilik.
    """
    from app.models.agent_config import AgentConfig
    from agents.futures.monitor_config import tp_lane_key, failfast_gap_key

    reco = await recommend_exit_params(days=days)
    if reco.get("status") != "ok":
        return reco

    planned, skipped = [], []

    # M3 — gap fail-fast per lane. Dipasang lewat jalur yang sama supaya satu
    # tombol menerapkan seluruh hasil belajar sisi keluar, bukan tersebar.
    ff = await recommend_failfast_params(days=days)
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
            "note": ("angka tersimpan tapi BELUM berpengaruh — nyalakan "
                     "futures.monitor_exit_learning_enabled untuk memakainya")}
