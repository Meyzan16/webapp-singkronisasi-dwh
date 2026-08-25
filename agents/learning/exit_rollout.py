"""Penyalaan bertahap parameter KELUAR — satu lane dulu, dengan bukti (M5).

Masalah yang diselesaikan: sampai M4, hasil belajar sisi keluar berhenti sebagai
rekomendasi. Menyalakannya adalah satu saklar biner untuk SEMUA lane sekaligus,
tanpa baseline pembanding dan tanpa jalan pulang otomatis bila ternyata memburuk.

Modul ini memberi sisi KELUAR tahapan yang sudah lama dimiliki sisi MASUK
(`shadow → canary → champion` di `futures_adaptive_model`), tapi per
**(lane × parameter)**:

    shadow      angka tercatat, monitor mengabaikannya. Baseline diukur di sini.
    canary      berlaku untuk SATU lane saja.
    active      lolos gate; tetap diawasi.
    rolled_back gagal gate; nilai dikembalikan otomatis.

Tiga disiplin yang membuat ini bukan sekadar tombol:

1. **Baseline direkam SEBELUM angka berlaku.** Tanpa pembanding, "membaik" cuma
   klaim. Pelajaran dari angka "116 terbukti membaik" yang ternyata menyesatkan.
2. **Satu lane dalam canary pada satu waktu.** Kalau dua lane dinyalakan bersama
   dan hasilnya membaik, tak ada cara tahu lane mana penyebabnya.
3. **Hanya exit yang terjadi SESUDAH aktivasi yang dihitung.** Posisi yang sudah
   terbuka memakai parameter lama; memasukkannya akan mengencerkan hasil.

Modul ini tidak pernah menyalakan apa pun sendiri — `advance()` dipanggil oleh
loop learning, dan naik ke canary tetap butuh perintah eksplisit.
"""

from __future__ import annotations

import json
import time

import structlog
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.agent_config import AgentConfig
from app.models.futures_exit_event import FuturesExitEvent
from app.models.futures_exit_rollout import FuturesExitRollout

logger = structlog.get_logger(__name__)

#: Parameter keluar yang boleh melewati tahapan ini, dipetakan ke kunci config
#: masing-masing. Fungsi, bukan dict literal, supaya kunci per-lane selalu
#: diturunkan dari sumber yang sama dengan yang dibaca monitor.
def param_config_key(param: str, lane: str, market: str = "futures") -> tuple[str, str]:
    """Return `(grup_config, kunci)` untuk sebuah parameter keluar.

    Grup ikut dikembalikan karena SPOT dan FUTURES menyimpan ambangnya di grup
    `agent_config` yang berbeda — menulis ke grup yang salah akan "berhasil"
    tanpa error tapi tak pernah dibaca monitor mana pun.
    """
    if market == "spot":
        from agents.opportunity import monitor_config as scfg
        if param == "tp_atr_mult":
            return "spot", scfg.tp_lane_key(lane)
        if param in GLOBAL_PARAMS:
            return "spot", GLOBAL_PARAMS[param]
        if param in COMPOSITE_PARAMS:
            return "spot", COMPOSITE_PARAMS[param]["spot"][0]
        raise ValueError(f"parameter keluar SPOT tak dikenal: {param}")

    from agents.futures import monitor_config as mcfg
    if param == "tp_atr_mult":
        return "futures", mcfg.tp_lane_key(lane)
    if param == "failfast_min_sl_gap":
        return "futures", mcfg.failfast_gap_key(lane)
    if param == "sl_max_pct":
        # Plafon lebar SL (% harga). Untuk bigmover inilah yang benar-benar
        # menentukan: 56% posisinya mentok plafon, sehingga `fallback_atr_mult`
        # yang dimaksudkan sadar-volatilitas jarang berlaku.
        from agents.futures import sl_config
        return "futures", sl_config.sl_key("max_pct", lane)
    if param in GLOBAL_PARAMS:
        return "futures", GLOBAL_PARAMS[param]
    if param in COMPOSITE_PARAMS:
        return "futures", COMPOSITE_PARAMS[param]["futures"][0]
    raise ValueError(f"parameter keluar tak dikenal: {param}")


# ── Parameter MAJEMUK: satu baris rollout, beberapa kunci config ─────────────
#
# Tangga TP adalah tiga angka yang HARUS bergerak bersama. Tiga baris terpisah
# akan salah dua kali: aturan satu-canary-per-market memblokir dua sisanya, dan
# TP1 yang berubah sendirian mengubah BENTUK tangganya — hasilnya tak lagi
# mencerminkan usulan mana pun.
#
# Ini juga parameter sisi MASUK pertama yang melewati tahapan ini. Mekanismenya
# sengaja dipakai ulang, bukan disalin: sisi SPOT dan katalog Formulas dua-duanya
# pernah lahir sebagai salinan lalu menyimpang diam-diam.
COMPOSITE_PARAMS: dict[str, dict[str, tuple[str, ...]]] = {
    "entry_tp_ladder": {
        "futures": ("bigmover_tp1_atr_mult", "bigmover_tp2_atr_mult",
                    "bigmover_tp3_atr_mult"),
        "spot":     ("bigmover_tp1_pct", "bigmover_tp2_pct", "bigmover_tp3_pct"),
    },
}


def composite_keys(param: str, market: str) -> tuple[str, ...]:
    """Kunci config yang ditulis sebuah parameter majemuk, terurut TP1→TP3."""
    return COMPOSITE_PARAMS.get(param, {}).get(market, ())


#: Parameter yang BUKAN per-lane. Populasi "posisi yang menyentuh TP1" terlalu
#: kecil untuk dibelah per lane — dibelah empat, tak satu pun lane akan pernah
#: mencapai ambang sampel, dan mesin belajar diam selamanya tanpa alasan yang
#: terlihat. Kunci di sini dipetakan LANGSUNG ke nama kunci `agent_config` milik
#: `agents/futures/monitor_config.py`.
GLOBAL_PARAMS: dict[str, str] = {
    "trail_lock_after_tp1":  "monitor_trail_lock_after_tp1_frac",
    "trail_advance_tp1_tp2": "monitor_trail_advance_tp1_tp2_frac",
}

#: Lane sentinel untuk parameter global. Wajib dipakai supaya dua baris rollout
#: dengan lane berbeda tak menulis kunci config yang SAMA — pemeriksaan duplikat
#: memakai (market, lane, param), jadi tanpa sentinel duplikatnya lolos.
GLOBAL_LANE = "all"

# ── Ingatan atas percobaan yang sudah ditolak ────────────────────────────────
#
# Recommender menurunkan angka dari ledger tiap kali dipanggil. Ledger tidak
# berubah hanya karena sebuah percobaan gagal, jadi tanpa ingatan ia akan
# MENGUSULKAN ULANG hal yang baru saja terbukti merugikan — bahkan dengan angka
# yang lebih ekstrem.
#
# Terukur 12 Agu, beberapa menit sesudah usul-otomatis dinyalakan:
#   id=7  futures/bigmover tp_atr_mult 0,526 -> DIBALIK (expectancy -2,03 vs
#         baseline +0,036, n=15)
#   id=10 futures/bigmover tp_atr_mult 0,431 -> diusulkan lagi 18 jam kemudian,
#         lane sama, parameter sama, KOMPRESI LEBIH KETAT.
#
# Tanpa penjaga ini, otomatisasi justru memutar ulang eksperimen gagal.

#: Berapa lama penolakan diingat. Bukan selamanya: pasar berubah, dan angka yang
#: merugikan bulan lalu belum tentu merugikan bulan depan.
REJECT_MEMORY_DAYS = 14

#: Arah "lebih agresif" tiap parameter. Ingatan hanya memblokir usulan yang
#: SETIDAKNYA SEEKSTREM yang sudah ditolak DI ARAH YANG SAMA — arah sebaliknya
#: belum pernah diuji, jadi memblokirnya berarti menyimpulkan dari ketiadaan
#: bukti.
_ARAH_AGRESIF: dict[str, int] = {
    "tp_atr_mult":           -1,   # makin KECIL = TP makin dikompresi
    "failfast_min_sl_gap":   +1,   # makin BESAR = fail-fast makin sering diblokir
    "trail_lock_after_tp1":  +1,   # makin BESAR = kunci sesudah TP1 makin ketat
    "trail_advance_tp1_tp2": -1,   # makin KECIL = lantai naik makin dini
    "sl_max_pct":            -1,   # makin KECIL = SL makin sempit, makin mudah terpotong
    # Majemuk: dinilai dari anak tangga PERTAMA (`proposed_value`), karena TP1
    # yang paling menentukan seberapa sering posisi keluar lebih awal. Ini
    # perbandingan PARSIAL — tangga dengan TP1 sama tapi ekor berbeda dianggap
    # setara. Disebut terus terang di sini supaya tak dikira menyeluruh.
    "entry_tp_ladder":       -1,   # TP1 makin KECIL = target makin dipangkas
}


async def _ditolak_dgn_bukti(session, market: str, lane: str, param: str,
                             value: float) -> dict | None:
    """Penolakan berbasis BUKTI yang menutupi nilai ini, bila ada.

    Yang dihitung sebagai bukti hanya canary yang benar-benar sempat dinilai
    (`observed_n` terisi). Baris yang dibalik manual atau digeser karena macet
    TIDAK membuktikan apa pun — memblokir berdasarkan itu akan mengunci lane
    hanya karena pemiliknya pernah mengubah prioritas.
    """
    batas = time.time() - REJECT_MEMORY_DAYS * 86400
    rows = list((await session.execute(select(FuturesExitRollout).where(
        FuturesExitRollout.market == market,
        FuturesExitRollout.lane == lane,
        FuturesExitRollout.param == param,
        FuturesExitRollout.stage == "rolled_back",
    ))).scalars().all())

    arah = _ARAH_AGRESIF.get(param, 0)
    for r in rows:
        if (r.observed_n or 0) < CANARY_MIN_OUTCOMES:
            continue                      # dibalik manual/macet — bukan bukti
        if (r.decided_at or 0) < batas:
            continue                      # sudah terlalu tua untuk mengikat
        ditolak = float(r.proposed_value or 0.0)
        lebih_ekstrem = (
            (arah < 0 and value <= ditolak)
            or (arah > 0 and value >= ditolak)
            or (arah == 0 and abs(value - ditolak) < 1e-9)
        )
        if lebih_ekstrem:
            return {
                "id": r.id, "nilai_ditolak": ditolak,
                "observed_n": r.observed_n,
                "observed_expectancy": r.observed_expectancy,
                "baseline_expectancy": r.baseline_expectancy,
                "umur_jam": round((time.time() - (r.decided_at or 0)) / 3600, 1),
            }
    return None


#: Parameter yang boleh melewati tahapan, per market. SPOT belum punya padanan
#: fail-fast — monitornya memakai pemicu lain (rotasi, trend_reversal), dan
#: memaksakan parameter futures ke sana akan menulis kunci yang tak pernah dibaca.
SUPPORTED_PARAMS_BY_MARKET: dict[str, tuple[str, ...]] = {
    "futures": ("tp_atr_mult", "failfast_min_sl_gap",
                "trail_lock_after_tp1", "trail_advance_tp1_tp2",
                "entry_tp_ladder", "sl_max_pct"),
    # SPOT kini punya kunci config sendiri untuk kedua parameter trailing, jadi
    # usulannya benar-benar sampai ke monitor. Fail-fast tetap khusus futures —
    # monitor SPOT memakai pemicu lain (rotasi, trend_reversal).
    "spot": ("tp_atr_mult", "trail_lock_after_tp1", "trail_advance_tp1_tp2",
             "entry_tp_ladder"),
}

SUPPORTED_PARAMS: tuple[str, ...] = SUPPORTED_PARAMS_BY_MARKET["futures"]

#: Exit minimum sesudah aktivasi sebelum canary boleh diputuskan. Di bawah ini
#: hasilnya belum bisa dibedakan dari kebetulan.
CANARY_MIN_OUTCOMES = 15

#: Baseline minimum — tanpa pembanding yang layak, kenaikan apa pun tak berarti.
BASELINE_MIN_OUTCOMES = 10

#: Canary lulus bila expectancy-nya minimal sebaik baseline dikurangi toleransi
#: ini (dalam % P&L). Toleransi kecil mencegah rollback karena derau, tapi tetap
#: menolak perubahan yang benar-benar memburuk.
CANARY_TOLERANCE_PCT = 0.25


def _stats(rows: list[FuturesExitEvent]) -> tuple[int, float | None, float | None]:
    pnls = [r.pnl_pct for r in rows if r.pnl_pct is not None]
    if not pnls:
        return len(rows), None, None
    wins = sum(1 for p in pnls if p > 0)
    return (len(pnls),
            round(sum(pnls) / len(pnls), 4),
            round(100.0 * wins / len(pnls), 1))


def _komposisi(rows: list[FuturesExitEvent]) -> str:
    """Ringkas alasan tutup selama canary, mis. `sl_hit×8, sl_plus×5, fail_fast×1`.

    Canary dinilai dari expectancy SELURUH lane, padahal sebuah parameter belum
    tentu menyentuh semua exit di dalamnya. Terukur 24 Agu: canary
    `failfast_min_sl_gap` dinilai dari 14 exit, padahal hanya **1** yang lewat
    jalur fail-fast — kerugiannya datang dari `sl_hit` yang tak disentuhnya.

    Komposisi ini tidak mengubah vonis; ia membuat vonis bisa dibaca. Tanpa ini,
    "dibalik: expectancy di bawah baseline" terbaca seolah parameternya bersalah,
    padahal buktinya bisa saja tak menyinggung parameter itu sama sekali.
    """
    from collections import Counter
    c = Counter((r.close_reason or "?") for r in rows)
    return ", ".join(f"{k}×{v}" for k, v in c.most_common())


#: Parameter yang berlaku SAAT POSISI DIBUKA, bukan saat ditutup.
#:
#: Tangga TP dibekukan di entry: posisi yang dibuka SEBELUM canary membawa
#: tangga lama sampai mati. Menyaringnya dengan `closed_at` — cara yang benar
#: untuk parameter keluar — akan menghitung posisi ber-tangga LAMA sebagai hasil
#: canary, dan canary dinilai dari sampel yang separuhnya bukan miliknya.
#: `sl_max_pct` ikut di sini karena lebar SL DIPASANG saat posisi dibuka. Posisi
#: yang sudah terbuka saat canary menyala membawa SL lama sampai mati — menyaring
#: dengan `closed_at` akan menghitungnya sebagai hasil canary, dan plafon baru
#: dinilai dari posisi yang tak pernah memakainya.
ENTRY_SIDE_PARAMS: frozenset[str] = frozenset({"entry_tp_ladder", "sl_max_pct"})


async def _lane_exits(session, lane: str, market: str = "futures",
                      since: float | None = None,
                      until: float | None = None, limit: int = 500,
                      by_entry: bool = False) -> list:
    q = select(FuturesExitEvent).where(FuturesExitEvent.market == market)
    # Parameter global memakai lane sentinel `all` — memfilter kolom lane ke
    # nilai itu akan mengembalikan NOL baris, dan canary-nya tak akan pernah
    # bisa dievaluasi (gagal senyap, bukan error).
    if lane != GLOBAL_LANE:
        q = q.where(FuturesExitEvent.lane == lane)
    if since is not None:
        # Parameter sisi MASUK disaring dari kapan posisi DIBUKA — lihat
        # ENTRY_SIDE_PARAMS. Memakai closed_at akan memasukkan posisi yang
        # membawa tangga LAMA ke dalam sampel canary.
        q = q.where((FuturesExitEvent.entry_at >= since) if by_entry
                    else (FuturesExitEvent.closed_at >= since))
    if until is not None:
        q = q.where(FuturesExitEvent.closed_at < until)
    q = q.order_by(FuturesExitEvent.closed_at.desc()).limit(limit)
    return list((await session.execute(q)).scalars().all())


async def _config_value(session, group: str, key: str) -> tuple[AgentConfig | None, float]:
    """Baris config + nilainya. `group` WAJIB disebut — SPOT dan FUTURES memakai
    grup berbeda, dan salah grup berarti menulis ambang yang tak pernah dibaca."""
    row = (await session.execute(select(AgentConfig).where(
        AgentConfig.agent_group == group, AgentConfig.key == key,
    ))).scalar_one_or_none()
    return row, (row.value_num if row else 0.0)


# ── Tahap 1: catat usulan sebagai shadow ──────────────────────────────────────

async def propose(lane: str, param: str, value: float, reason: str = "",
                  market: str = "futures", values: dict | None = None) -> dict:
    """Catat usulan sebagai `shadow` beserta baseline lane saat ini.

    Baseline diambil SEKARANG — sebelum angka berlaku — karena itulah satu-satunya
    saat pembanding masih bersih.

    `values` diisi untuk parameter MAJEMUK (mis. tangga TP): peta kunci→nilai
    yang akan ditulis bersamaan saat naik ke canary. `value` tetap diisi anak
    tangga pertama supaya kode dan tampilan lama tak perlu tahu soal ini.
    """
    didukung = SUPPORTED_PARAMS_BY_MARKET.get(market, ())
    if param not in didukung:
        return {"status": "param_tak_dikenal", "param": param, "market": market,
                "supported": list(didukung)}
    if param in GLOBAL_PARAMS and lane != GLOBAL_LANE:
        return {"status": "lane_salah", "param": param, "lane": lane,
                "harus": GLOBAL_LANE,
                "why": ("parameter global — lane per-koin akan membuat beberapa "
                        "baris rollout menulis kunci config yang sama")}
    if not is_db_available():
        return {"status": "db_unavailable"}

    group, key = param_config_key(param, lane, market)
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.market == market,
            FuturesExitRollout.lane == lane, FuturesExitRollout.param == param,
            FuturesExitRollout.stage.in_(["shadow", "canary", "active"]),
        ))).scalars().first()
        if existing:
            return {"status": "sudah_ada", "stage": existing.stage,
                    "id": existing.id, "proposed_value": existing.proposed_value}

        # Jangan mengusulkan ulang apa yang sudah TERBUKTI merugikan.
        _tolak = await _ditolak_dgn_bukti(session, market, lane, param, value)
        if _tolak:
            return {
                "status": "ditolak_dgn_bukti", "market": market, "lane": lane,
                "param": param, "value": value, "sebelumnya": _tolak,
                "why": (f"nilai {value} setidaknya seekstrem {_tolak['nilai_ditolak']} "
                        f"yang sudah diuji (id={_tolak['id']}, n={_tolak['observed_n']}) "
                        f"dan dibalik karena expectancy {_tolak['observed_expectancy']} "
                        f"di bawah baseline {_tolak['baseline_expectancy']}. "
                        f"Ingatan berlaku {REJECT_MEMORY_DAYS} hari; arah sebaliknya "
                        f"tetap boleh diusulkan."),
            }

        _, current = await _config_value(session, group, key)
        n, exp, wr = _stats(await _lane_exits(session, lane, market))
        row = FuturesExitRollout(
            market=market, lane=lane, param=param, stage="shadow",
            proposed_value=value, previous_value=current,
            baseline_n=n, baseline_expectancy=exp, baseline_win_rate=wr,
            reason=reason or "usulan dari ledger keluar",
            proposed_json=(json.dumps({"keys": values}, ensure_ascii=False)
                           if values else None),
        )
        session.add(row)
        await session.commit()
        rid = row.id

    logger.info("exit_rollout_proposed", market=market, lane=lane, param=param,
                value=value, id=rid)
    return {"status": "ok", "id": rid, "stage": "shadow", "market": market, "lane": lane,
            "param": param, "proposed_value": value, "previous_value": current,
            "baseline": {"n": n, "expectancy_pct": exp, "win_rate": wr}}


# ── Tahap 2: naikkan ke canary (menulis nilai ke config) ──────────────────────

async def start_canary(rollout_id: int) -> dict:
    """Berlakukan usulan untuk SATU lane. Ditolak bila baseline belum cukup, atau
    bila sudah ada lane lain yang sedang canary — dua perubahan bersamaan membuat
    hasilnya mustahil ditafsirkan."""
    if not is_db_available():
        return {"status": "db_unavailable"}

    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.id == rollout_id))).scalar_one_or_none()
        if row is None:
            return {"status": "tak_ditemukan"}
        if row.stage != "shadow":
            return {"status": "bukan_shadow", "stage": row.stage}
        if row.baseline_n < BASELINE_MIN_OUTCOMES:
            return {"status": "baseline_kurang", "baseline_n": row.baseline_n,
                    "required": BASELINE_MIN_OUTCOMES,
                    "reason": "tanpa pembanding yang layak, perbaikan apa pun tak bisa dibuktikan"}

        # Satu canary per MARKET, bukan satu untuk seluruh sistem.
        #
        # Alasan aturan ini (M5) adalah agar hasil bisa diatribusikan: kalau dua
        # lane berjalan bersama dan hasilnya membaik, tak ada cara tahu mana
        # penyebabnya. Tapi atribusi itu hanya kabur bila keduanya diukur dari
        # kumpulan exit yang SAMA. `evaluate()` menyaring `row.market` DAN
        # `row.lane`, jadi canary SPOT dan FUTURES membaca ledger yang terpisah
        # dan mustahil saling mengacaukan.
        #
        # Ruang lingkup global sempat menahan canary FUTURES hanya karena SPOT
        # sedang menguji lane lain — pembatasan yang tak menambah keamanan apa
        # pun, cuma memperlambat pembuktian.
        busy = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.stage == "canary",
            FuturesExitRollout.market == row.market,
        ))).scalars().first()
        if busy is not None:
            return {"status": "canary_lain_berjalan", "market": row.market,
                    "lane": busy.lane, "param": busy.param, "id": busy.id,
                    "reason": f"satu lane per market pada satu waktu — {row.market} "
                              f"sedang menguji {busy.lane}, dan menjalankan dua "
                              f"bersamaan membuat hasilnya tak bisa diatribusikan"}

        group, key = param_config_key(row.param, row.lane, row.market)

        # Parameter MAJEMUK menulis semua kuncinya sekaligus. Menulis sebagian
        # akan meninggalkan tangga TP setengah berubah — bentuk yang tak pernah
        # diusulkan siapa pun, dan hasilnya tak mencerminkan apa-apa.
        _keys = composite_keys(row.param, row.market)
        current = None          # diisi kedua cabang — dipakai blok `return`
        if _keys:
            _usul = json.loads(row.proposed_json or "{}").get("keys", {})
            _lama: dict[str, float] = {}
            for k in _keys:
                cr, cur = await _config_value(session, group, k)
                if cr is None:
                    return {"status": "baris_config_hilang", "key": k}
                _lama[k] = cur
                cr.value_num = float(_usul[k])
                cr.updated_at = time.time()
                cr.updated_by = "exit_rollout"
            row.proposed_json = json.dumps({"keys": _usul, "previous": _lama},
                                           ensure_ascii=False)
            row.previous_value = _lama[_keys[0]]
            current = _lama[_keys[0]]
            row.reason = (f"canary majemuk: " +
                          "; ".join(f"{k} {_lama[k]} -> {_usul[k]}" for k in _keys) +
                          f"; baseline n={row.baseline_n} "
                          f"expectancy={row.baseline_expectancy}")
        else:
            cfg_row, current = await _config_value(session, group, key)
            if cfg_row is None:
                return {"status": "baris_config_hilang", "key": key}
            row.previous_value = current
            cfg_row.value_num = row.proposed_value
            cfg_row.updated_at = time.time()
            cfg_row.updated_by = "exit_rollout"
            row.reason = (f"canary: {key} {current} -> {row.proposed_value}; "
                          f"baseline n={row.baseline_n} "
                          f"expectancy={row.baseline_expectancy}")
        row.stage = "canary"
        row.activated_at = time.time()
        await session.commit()
        out = {"status": "ok", "stage": "canary", "id": row.id,
               "market": row.market, "lane": row.lane,
               "param": row.param, "key": key, "from": current,
               "to": row.proposed_value,
               "note": ("nilai sudah tertulis, TAPI monitor baru memakainya bila "
                        f"{row.market}.monitor_exit_learning_enabled menyala")}

    logger.info("exit_rollout_canary_started", **{k: out[k] for k in ("lane", "param", "to")})
    return out


# ── Tahap 3: evaluasi & putuskan ──────────────────────────────────────────────

async def evaluate(rollout_id: int) -> dict:
    """Bandingkan hasil SESUDAH aktivasi dengan baseline, lalu putuskan.

    Batas sampelnya BERBEDA menurut sisi parameternya:

    * sisi KELUAR — disaring dari `closed_at`. Posisi yang sudah terbuka saat
      canary menyala langsung memakai aturan keluar yang baru, jadi exit-nya
      memang milik canary.
    * sisi MASUK (`ENTRY_SIDE_PARAMS`) — disaring dari `entry_at`. Tangga TP
      dibekukan saat entry, jadi posisi yang dibuka sebelum canary membawa
      tangga LAMA sampai mati. Menghitungnya akan menilai canary dari sampel
      yang separuhnya bukan miliknya.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}

    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.id == rollout_id))).scalar_one_or_none()
        if row is None:
            return {"status": "tak_ditemukan"}
        if row.stage != "canary":
            return {"status": "bukan_canary", "stage": row.stage}

        after = await _lane_exits(session, row.lane, row.market,
                                  since=row.activated_at or 0.0,
                                  by_entry=row.param in ENTRY_SIDE_PARAMS)
        n, exp, wr = _stats(after)
        row.observed_n, row.observed_expectancy, row.observed_win_rate = n, exp, wr

        if n < CANARY_MIN_OUTCOMES:
            await session.commit()
            return {"status": "mengumpulkan", "n": n, "required": CANARY_MIN_OUTCOMES,
                    "lane": row.lane, "param": row.param}

        base = row.baseline_expectancy if row.baseline_expectancy is not None else 0.0
        lulus = exp is not None and exp >= base - CANARY_TOLERANCE_PCT
        row.decided_at = time.time()
        komposisi = _komposisi(after)

        if lulus:
            row.stage = "active"
            row.reason = (f"lulus: expectancy {exp} vs baseline {base} "
                          f"(toleransi {CANARY_TOLERANCE_PCT}), n={n} [{komposisi}]")
        else:
            group, key = param_config_key(row.param, row.lane, row.market)
            cfg_row, _ = await _config_value(session, group, key)
            if cfg_row is not None:
                cfg_row.value_num = row.previous_value
                cfg_row.updated_at = time.time()
                cfg_row.updated_by = "exit_rollout_rollback"
            row.stage = "rolled_back"
            row.reason = (f"dibalik: expectancy {exp} di bawah baseline {base} "
                          f"(toleransi {CANARY_TOLERANCE_PCT}), n={n} [{komposisi}]; "
                          f"{key} dikembalikan ke {row.previous_value}")

        await session.commit()
        out = {"status": "ok", "stage": row.stage, "id": row.id,
               "market": row.market, "lane": row.lane,
               "param": row.param, "reason": row.reason,
               "baseline": {"n": row.baseline_n, "expectancy_pct": base,
                            "win_rate": row.baseline_win_rate},
               "observed": {"n": n, "expectancy_pct": exp, "win_rate": wr,
                            "close_reasons": komposisi}}

    logger.info("exit_rollout_decided", lane=out["lane"], param=out["param"],
                stage=out["stage"])
    return out


async def rollback(rollout_id: int, reason: str = "dibalik manual") -> dict:
    """Kembalikan parameter ke nilai sebelumnya, apa pun tahapannya.

    Tersedia untuk `active` juga — parameter yang sudah lulus gate tetap boleh
    dibatalkan tanpa harus menunggu evaluasi berikutnya.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(FuturesExitRollout).where(
            FuturesExitRollout.id == rollout_id))).scalar_one_or_none()
        if row is None:
            return {"status": "tak_ditemukan"}
        if row.stage not in ("canary", "active"):
            return {"status": "tak_bisa_dibalik", "stage": row.stage}

        group, key = param_config_key(row.param, row.lane, row.market)

        # Majemuk: kembalikan SEMUA kuncinya. Mengembalikan sebagian akan
        # meninggalkan tangga campuran — separuh nilai usulan, separuh nilai
        # lama — yang tak pernah diuji dan tak pernah dipilih siapa pun.
        _keys = composite_keys(row.param, row.market)
        if _keys:
            _lama = json.loads(row.proposed_json or "{}").get("previous", {})
            _pulih = []
            for k in _keys:
                cr, _ = await _config_value(session, group, k)
                if cr is not None and k in _lama:
                    cr.value_num = float(_lama[k])
                    cr.updated_at = time.time()
                    cr.updated_by = "exit_rollout_rollback"
                    _pulih.append(f"{k}->{_lama[k]}")
            row.reason = f"{reason}; dikembalikan: " + ", ".join(_pulih)
        else:
            cfg_row, _ = await _config_value(session, group, key)
            if cfg_row is not None:
                cfg_row.value_num = row.previous_value
                cfg_row.updated_at = time.time()
                cfg_row.updated_by = "exit_rollout_rollback"
            row.reason = f"{reason}; {key} dikembalikan ke {row.previous_value}"
        row.stage = "rolled_back"
        row.decided_at = time.time()
        await session.commit()
        out = {"status": "ok", "stage": "rolled_back", "id": row.id,
               "market": row.market, "lane": row.lane, "param": row.param, "key": key,
               "restored_to": row.previous_value}
    logger.info("exit_rollout_rolled_back", lane=out["lane"], param=out["param"])
    return out


async def propose_from_recommendations(days: int = 90, market: str = "futures") -> dict:
    """Alirkan usulan mesin belajar ke antrean tahapan ini.

    Inilah sambungan antara `exit_learning` (yang menghitung angka) dan tahapan
    penyalaan (yang menguji angka itu di dunia nyata). Tanpa sambungan ini, dua
    lapisan itu hidup terpisah dan hasil belajar berhenti sebagai laporan.

    Tidak ada yang berlaku di sini — semua masuk sebagai `shadow`.
    """
    from agents.learning.exit_learning import (
        recommend_exit_params, recommend_failfast_params,
    )

    hasil, dilewati = [], []

    didukung = SUPPORTED_PARAMS_BY_MARKET.get(market, ())
    tp = await recommend_exit_params(days=days, market=market)
    for rec in tp.get("recommendations", []):
        if rec.get("status") != "ok" or not rec.get("suggested_tp_atr"):
            dilewati.append({"lane": rec.get("lane"), "param": "tp_atr_mult",
                             "reason": rec.get("status", "usulan_kosong")})
            continue
        if rec.get("premature_frac", 0.0) >= 0.5:
            dilewati.append({"lane": rec["lane"], "param": "tp_atr_mult",
                             "reason": "mayoritas_exit_prematur"})
            continue
        _r = await propose(
            rec["lane"], "tp_atr_mult", rec["suggested_tp_atr"], market=market,
            reason=f"TP realistis dari {rec['n']} exit; "
                   f"akan tersentuh ~{rec.get('would_be_reached_pct')}%")
        # Usulan yang ditolak ingatan BUKAN usulan — menaruhnya di `diusulkan`
        # membuat laporan terbaca seolah antrean bertambah padahal tidak.
        (dilewati if _r.get("status") == "ditolak_dgn_bukti" else hasil).append(_r)

    # Fail-fast hanya ada di futures; melewatinya untuk market lain lebih jujur
    # daripada menulis kunci yang tak pernah dibaca monitornya.
    if "failfast_min_sl_gap" not in didukung:
        return {"status": "ok", "market": market, "diusulkan": hasil, "dilewati": dilewati}

    ff = await recommend_failfast_params(days=days, market=market)
    for rec in ff.get("recommendations", []):
        if rec.get("status") != "ok":
            dilewati.append({"lane": rec.get("lane"), "param": "failfast_min_sl_gap",
                             "reason": rec.get("status")})
            continue
        _r = await propose(
            rec["lane"], "failfast_min_sl_gap", rec["suggested_gap"], market=market,
            reason=rec.get("note", ""))
        (dilewati if _r.get("status") == "ditolak_dgn_bukti" else hasil).append(_r)

    await _usulkan_tangga_masuk(days, market, hasil, dilewati)
    await _usulkan_lebar_sl(days, market, hasil, dilewati)
    return {"status": "ok", "market": market, "diusulkan": hasil, "dilewati": dilewati}


async def _usulkan_lebar_sl(days: int, market: str, hasil: list, dilewati: list) -> None:
    """Alirkan usulan lebar SL (M4b) ke antrean — satuannya diterjemahkan dulu.

    `recommend_sl_width()` bekerja dalam kelipatan ATR, tapi yang benar-benar
    menentukan lebar SL adalah PLAFON dalam % harga: 56% posisi bigmover mentok
    plafon 8%, sehingga `fallback_atr_mult` yang dimaksudkan sadar-volatilitas
    jarang berlaku. Mengusulkan angka ATR ke kunci `max_pct` akan menulis "0,9"
    ke sebuah plafon persen — SL 0,9% harga, jauh lebih sempit dari yang dimaksud,
    tanpa satu pun error muncul.
    """
    if "sl_max_pct" not in SUPPORTED_PARAMS_BY_MARKET.get(market, ()):
        return

    from agents.learning.exit_learning import recommend_sl_width
    sl = await recommend_sl_width(days=days, market=market)
    if sl.get("status") != "ok":
        return

    for rec in sl.get("recommendations", []):
        lane = rec.get("lane")
        if rec.get("status") != "ok":
            dilewati.append({"lane": lane, "param": "sl_max_pct",
                             "reason": rec.get("status")})
            continue
        # ATR → % harga. Tanpa `proposed_sl_pct` (lane tanpa atr_pct) usulannya
        # DILEWATI, bukan ditebak: menebak satuan di sini menghasilkan plafon yang
        # tampak masuk akal tapi salah besaran.
        usulan_pct = rec.get("proposed_sl_pct")
        if not usulan_pct:
            dilewati.append({"lane": lane, "param": "sl_max_pct",
                             "reason": "atr_pct_tak_ada_utk_konversi"})
            continue
        _r = await propose(
            lane, "sl_max_pct", round(float(usulan_pct), 2), market=market,
            reason=(f"plafon SL dari MAE pemenang: terdalam {rec['mae_winner_max_atr']}× ATR "
                    f"pada {rec['n']} exit; {rec['winners_cut']} pemenang terpotong, "
                    f"{rec['losers_capped']} pecundang dihentikan lebih awal"
                    + (" [dibatasi step-cap]" if rec.get("step_capped") else "")))
        (dilewati if _r.get("status") == "ditolak_dgn_bukti" else hasil).append(_r)


async def _usulkan_tangga_masuk(days: int, market: str,
                                hasil: list, dilewati: list) -> None:
    """Alirkan tangga TP sisi MASUK ke antrean, sebagai SATU baris majemuk.

    Ketiga anak tangga bergerak utuh — lihat `COMPOSITE_PARAMS`. Tetap masuk
    `shadow`: tak ada yang berlaku sampai dinaikkan secara eksplisit.
    """
    from agents.learning.exit_learning import recommend_entry_tp_ladder
    for lane in ("bigmover",):
        lad = await recommend_entry_tp_ladder(days=days, market=market, lane=lane)
        if not lad.get("recommendation_ready"):
            dilewati.append({"lane": lane, "param": "entry_tp_ladder",
                             "reason": f"mfe_kurang ({lad.get('n_mfe')}/"
                                       f"{lad.get('required')})"})
            continue
        keys = composite_keys("entry_tp_ladder", market)
        vals = dict(zip(keys, lad["suggested_ladder"]))
        r = await propose(
            lane, "entry_tp_ladder", lad["suggested_ladder"][0], market=market,
            values=vals,
            reason=(f"tangga dari MFE n={lad['n_mfe']}: p50/p75/p90 = "
                    f"{lad['mfe_atr']['p50']}/{lad['mfe_atr']['p75']}"
                    f"/{lad['mfe_atr']['p90']} ATR"))
        (dilewati if r.get("status") == "ditolak_dgn_bukti" else hasil).append(r)


# ── Loop: maju sendiri sejauh yang aman ───────────────────────────────────────

async def advance(market: str | None = None) -> dict:
    """Evaluasi canary yang berjalan. Dipanggil loop scheduler tiap market.

    Sengaja TIDAK menaikkan shadow→canary sendiri: memberlakukan parameter baru
    ke keputusan trading tetap butuh perintah eksplisit.

    `market` WAJIB disebut pemanggil rutin. Tanpanya, satu loop mengevaluasi
    canary market lain — dan sampai 12 Agu itulah yang terjadi: canary SPOT
    hanya dinilai sebagai efek samping loop FUTURES, sehingga berhenti dinilai
    diam-diam setiap kali futures berhenti. Tak ada error, hanya canary yang
    membeku tanpa alasan yang terlihat.
    """
    if not is_db_available():
        return {"status": "db_unavailable"}
    async with AsyncSessionLocal() as session:
        q = select(FuturesExitRollout).where(FuturesExitRollout.stage == "canary")
        if market:
            q = q.where(FuturesExitRollout.market == market)
        ids = [r.id for r in (await session.execute(q)).scalars().all()]
    return {"status": "ok", "market": market or "semua",
            "evaluated": [await evaluate(i) for i in ids]}


async def status() -> dict:
    """Semua tahapan penyalaan beserta posisinya — untuk endpoint/UI."""
    if not is_db_available():
        return {"status": "db_unavailable"}
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(select(FuturesExitRollout).order_by(
            FuturesExitRollout.created_at.desc()).limit(100))).scalars().all())
        # Saklar belajar TERPISAH per market — dilaporkan keduanya supaya tak ada
        # yang mengira menyalakan satu berarti menyalakan dua-duanya.
        _, fut_on = await _config_value(session, "futures", "monitor_exit_learning_enabled")
        _, spot_on = await _config_value(session, "spot", "monitor_exit_learning_enabled")

        # Komposisi exit hanya dihitung untuk baris yang SEDANG canary — baris yang
        # sudah diputuskan membawa komposisinya di dalam `reason`, dan menghitung
        # ulang seratus baris riwayat tiap kali daftar dibuka tak sepadan.
        komposisi_canary: dict[int, str] = {}
        for r in rows:
            if r.stage != "canary" or not r.activated_at:
                continue
            after = await _lane_exits(session, r.lane, r.market,
                                      since=r.activated_at,
                                      by_entry=r.param in ENTRY_SIDE_PARAMS)
            if after:
                komposisi_canary[r.id] = _komposisi(after)

    return {
        "status": "ok",
        "learning_enabled": {"futures": fut_on > 0, "spot": spot_on > 0},
        # Saklarnya TERPISAH per market, jadi catatan ini harus menyebut market —
        # kalimat tunggal membuat orang mengira menyalakan satu = menyalakan dua.
        "note": ("Angka per-lane sebuah market baru dipakai keputusan bila "
                 "<market>.monitor_exit_learning_enabled market itu bernilai 1. "
                 "Selama 0, angkanya tersimpan dan tercatat tapi TIDAK menyentuh "
                 "satu pun keputusan."),
        "gates": {"canary_min_outcomes": CANARY_MIN_OUTCOMES,
                  "baseline_min_outcomes": BASELINE_MIN_OUTCOMES,
                  "canary_tolerance_pct": CANARY_TOLERANCE_PCT},
        "rollouts": [{
            "id": r.id, "market": r.market, "lane": r.lane, "param": r.param,
            "stage": r.stage,
            "proposed_value": r.proposed_value, "previous_value": r.previous_value,
            "baseline": {"n": r.baseline_n, "expectancy_pct": r.baseline_expectancy,
                         "win_rate": r.baseline_win_rate},
            "observed": {"n": r.observed_n, "expectancy_pct": r.observed_expectancy,
                         "win_rate": r.observed_win_rate,
                         # Komposisi alasan tutup selama canary. Tanpa ini, "expectancy
                         # di bawah baseline" terbaca seolah parameternya bersalah —
                         # padahal buktinya bisa tak menyinggung parameter itu sama
                         # sekali (terukur 24 Agu: 1 dari 14 exit).
                         "close_reasons": komposisi_canary.get(r.id)},
            "created_at": r.created_at, "activated_at": r.activated_at,
            "decided_at": r.decided_at, "reason": r.reason,
        } for r in rows],
    }
