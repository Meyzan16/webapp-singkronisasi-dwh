"""Aturan keluar FUTURES — enam mekanisme, dan SL selalu dinilai lebih dulu.

PLAN-FUTURES-AGENTIC.md Fase 4. Menggantikan 19 alasan tutup di `monitor.py`
(2.175 baris) dengan enam yang masing-masing punya alasan keberadaan yang bisa
diuji.

── Kenapa dipangkas jadi enam ────────────────────────────────────────────────
Dari 107 baris ledger keluar (5 Sep 2026), yang benar-benar terjadi hanyalah
segelintir; sisanya mekanisme yang saling tumpang tindih dan justru saling
mendahului. Tiga temuan yang membentuk modul ini:

  B2  SL TIDAK DIEKSEKUSI DI LEVELNYA. `fail_fast` dinilai di baris 939
      sementara cek SL baru di 1208 — dalam satu iterasi, harga yang SUDAH
      menembus SL ditangkap fail_fast lebih dulu lalu dilabeli salah. BLUAI:
      SL dipasang 7,99%, ditutup di −17,30% = 2,16x risiko yang direncanakan.
      Di sini SL dinilai PALING PERTAMA, selalu.

  B5  BREAKEVEN JADI PABRIK IMPAS. Rem dipasang di 40% jalan ke TP1 atau
      +1,5% absolut, mana yang lebih dulu. Karena TP1 dipasang 4-8 ATR
      (tak pernah tercapai), yang selalu menang adalah +1,5% — lalu pullback
      1,2% menyentuhnya. Hasilnya 31 trade `sl_plus` dengan rata-rata +$0,25,
      alias persis fee. Di sini breakeven baru boleh menyala setelah untungnya
      MELEBIHI biaya beberapa kali lipat.

  TP  TAK PERNAH TERCAPAI. TP dipasang 4-8 ATR sementara trade rata-rata hanya
      bergerak 0,67 ATR ke arah untung. Hanya 5 dari 112 (4%) menyentuh TP.
      Di sini TP1 default 1,2 ATR — jarak yang memang pernah dicapai — dengan
      sebagian posisi dibiarkan jalan sebagai pelari tanpa plafon.

`fail_fast` TIDAK ADA di sini: 11 trade, −$79, nol menang, dan ia pula yang
melabeli tembusan SL sebagai sesuatu yang lain.

── Sifat modul ini ───────────────────────────────────────────────────────────
MURNI: tak menyentuh DB, tak async, tak membaca jam. Seluruh keadaan masuk lewat
`ExitState`. Itu membuat setiap keputusan keluar bisa diuji dengan angka, dan
bisa DIPUTAR ULANG atas ledger historis sebelum satu pun posisi nyata dikelola.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Kosakata alasan keluar ────────────────────────────────────────────────────
# Delapan, titik. Tiap tambahan wajib punya bukti bahwa yang enam tak cukup.
SL_HIT = "sl_hit"
SL_PLUS = "sl_plus"          # trailing/breakeven menutup DI ATAS entry
TP1_HIT = "tp1_hit"          # parsial
TP2_HIT = "tp2_hit"          # parsial
TRAIL_HIT = "trail_hit"      # pelari kena trailing stop
TIME_STOP = "time_stop"
LIQ_GUARD = "liq_guard"
EMERGENCY = "emergency_close"

#: Alasan yang dihitung KERUGIAN NYATA oleh risk_gate (untuk streak & jeda).
REAL_LOSS_REASONS = frozenset({SL_HIT, LIQ_GUARD, EMERGENCY})


@dataclass(frozen=True)
class ExitParams:
    """Parameter aturan keluar. Semua dari `agent_config` (futures.exit_*)."""

    tp1_atr_mult: float          # jarak TP1 dalam kelipatan ATR
    tp2_atr_mult: float
    tp1_close_frac: float        # porsi posisi yang dijual di TP1
    tp2_close_frac: float
    be_arm_cost_mult: float      # breakeven menyala setelah untung >= ini x biaya
    be_arm_atr: float            # ...DAN >= sekian ATR
    be_lock_frac: float          # saat breakeven menyala, kunci sekian bagian untung
    trail_lock_frac: float       # sesudah TP1, kunci sekian bagian dari puncak
    max_hold_h: float
    time_stop_progress: float    # progres minimum (x risiko) agar lolos time-stop


@dataclass(frozen=True)
class ExitState:
    """Keadaan satu posisi pada satu saat. Semua eksplisit — tak ada yang diambil
    diam-diam dari luar, supaya replay historis dan keputusan live memakai jalan
    yang sama persis."""

    direction: str               # "LONG" | "SHORT"
    entry: float
    price: float                 # harga sekarang
    sl: float                    # SL yang BERLAKU (sudah termasuk trailing)
    atr_pct: float
    cost_pct: float              # biaya round-trip (%)
    risk_pct: float              # jarak SL awal dari entry (%)
    hold_minutes: float
    peak_pnl_pct: float          # gerak favorable terjauh sejauh ini (%)
    tp1_done: bool = False
    tp2_done: bool = False
    trail_active: bool = False
    # Wick — SL dinilai dari ekstrem, bukan harga penutupan, supaya tembusan
    # intra-candle tak lolos sampai tick berikutnya (bagian dari B2).
    low: Optional[float] = None
    high: Optional[float] = None


@dataclass(frozen=True)
class ExitDecision:
    """Keputusan + kenapa. `close_frac` 0 berarti tak menutup apa pun."""

    action: str                  # "hold" | "close" | "partial" | "move_sl"
    reason: str
    close_frac: float = 0.0
    close_price: Optional[float] = None
    new_sl: Optional[float] = None
    note: str = ""


def _pnl_pct(s: ExitState, price: Optional[float] = None) -> float:
    """P&L kotor (%) pada sebuah harga. Arah sudah diperhitungkan."""
    p = s.price if price is None else price
    if not s.entry:
        return 0.0
    return ((p - s.entry) if s.direction == "LONG" else (s.entry - p)) / s.entry * 100


def _favorable(s: ExitState, price: float) -> float:
    return _pnl_pct(s, price)


def sl_breached(s: ExitState) -> tuple[bool, float]:
    """Apakah SL tertembus, dan SEBERAPA JAUH harga melewatinya (%).

    Angka kedua itulah `sl_breach_pct` — bukti terukur untuk B2. Selama ini
    penyimpangan fill terhadap SL tak pernah dicatat, sehingga rugi 2,16x
    risiko hanya bisa ditemukan lewat forensik manual.
    """
    if not s.sl or not s.entry:
        return False, 0.0
    if s.direction == "LONG":
        ekstrem = s.low if s.low is not None else s.price
        if ekstrem <= s.sl:
            return True, max(0.0, (s.sl - ekstrem) / s.entry * 100)
    else:
        ekstrem = s.high if s.high is not None else s.price
        if ekstrem >= s.sl:
            return True, max(0.0, (ekstrem - s.sl) / s.entry * 100)
    return False, 0.0


def tp_level(s: ExitState, atr_mult: float) -> float:
    """Harga TP pada jarak `atr_mult` x ATR dari entry."""
    jarak = s.entry * (s.atr_pct * atr_mult) / 100
    return s.entry + jarak if s.direction == "LONG" else s.entry - jarak


def breakeven_price(s: ExitState) -> float:
    """Breakeven SEJATI = entry ditambah seluruh biaya. SL di entry polos masih
    rugi fee — itu yang membuat `breakeven_stop` rata-rata −$0,30."""
    geser = s.entry * s.cost_pct / 100
    return s.entry + geser if s.direction == "LONG" else s.entry - geser


def protective_price(s: ExitState, p: ExitParams) -> float:
    """Ke mana SL dipindahkan saat rem dipasang.

    BUKAN sekadar entry+biaya. Replay 5 Sep 2026 menunjukkan kenapa: memindahkan
    SL tepat ke breakeven berarti setiap kali rem itu tersentuh, hasilnya nol —
    menurut definisi. Menggeser SAAT rem menyala pun tak menolong, karena yang
    ditutup tetap posisi di titik impas. Itulah sebab 31 trade `sl_plus`
    menghasilkan rata-rata +$0,25, dan kenapa menaikkan ambang penyalaan dari 3x
    ke 8x biaya sama sekali tak mengurangi jumlahnya di replay.

    Jadi rem ini mengunci SEBAGIAN UNTUNG yang sudah dicapai, dengan entry+biaya
    hanya sebagai LANTAI. Kalau tersentuh, yang dibukukan untung nyata — kecil,
    tapi bukan nol.
    """
    untung = _pnl_pct(s)
    kunci_pct = max(s.cost_pct, untung * p.be_lock_frac)
    geser = s.entry * kunci_pct / 100
    return s.entry + geser if s.direction == "LONG" else s.entry - geser


def breakeven_armed(s: ExitState, p: ExitParams) -> bool:
    """Boleh memasang rem breakeven?

    DUA syarat, dan keduanya wajib — inilah perbaikan B5:
      * untung sekarang melebihi `be_arm_cost_mult` x biaya (jadi kalaupun
        langsung tersentuh, hasilnya tetap di atas biaya, bukan impas);
      * untung juga melebihi `be_arm_atr` x ATR (jadi tak menyala hanya karena
        derau harian koin yang volatil).
    """
    untung = _pnl_pct(s)
    return (untung >= p.be_arm_cost_mult * s.cost_pct
            and untung >= p.be_arm_atr * s.atr_pct)


def evaluate(s: ExitState, p: ExitParams) -> ExitDecision:
    """Satu keputusan keluar. URUTANNYA ADALAH BAGIAN DARI ATURAN.

    SL dinilai paling pertama — bukan karena rapi, tapi karena mendahulukan
    mekanisme lain persis itulah cara BLUAI ditutup di 2,16x risiko dan
    dilabeli `fail_fast`.
    """
    # ── 0. SL — SELALU pertama ────────────────────────────────────────────────
    kena, breach = sl_breached(s)
    if kena:
        untung_di_sl = _favorable(s, s.sl)
        # SL yang sudah bergerak melewati breakeven menutup dengan UNTUNG.
        # Membedakannya penting: `sl_plus` bukan kerugian nyata, dan risk_gate
        # tak boleh menghitungnya sebagai bagian dari rentetan kekalahan.
        reason = SL_PLUS if untung_di_sl > 0 else SL_HIT
        return ExitDecision(action="close", reason=reason, close_frac=1.0,
                            close_price=s.sl,
                            note=f"sl_breach_pct={breach:.3f}")

    # ── 2. TP1 — parsial, di jarak yang MEMANG pernah dicapai ────────────────
    if not s.tp1_done:
        lvl = tp_level(s, p.tp1_atr_mult)
        tercapai = (s.high if s.high is not None else s.price) >= lvl \
            if s.direction == "LONG" else \
            (s.low if s.low is not None else s.price) <= lvl
        if tercapai:
            return ExitDecision(action="partial", reason=TP1_HIT,
                                close_frac=p.tp1_close_frac, close_price=lvl,
                                new_sl=protective_price(s, p),
                                note=f"TP1 {p.tp1_atr_mult}xATR; sisanya dilindungi")

    # ── 3. TP2 — parsial lagi; sisanya jadi PELARI tanpa plafon ──────────────
    if s.tp1_done and not s.tp2_done:
        lvl = tp_level(s, p.tp2_atr_mult)
        tercapai = (s.high if s.high is not None else s.price) >= lvl \
            if s.direction == "LONG" else \
            (s.low if s.low is not None else s.price) <= lvl
        if tercapai:
            return ExitDecision(action="partial", reason=TP2_HIT,
                                close_frac=p.tp2_close_frac, close_price=lvl,
                                note=f"TP2 {p.tp2_atr_mult}xATR; sisa posisi jadi pelari")

    # ── 5. Trailing — hanya SESUDAH TP1, mengunci bagian dari puncak ─────────
    if s.tp1_done and s.peak_pnl_pct > 0:
        kunci_pct = s.peak_pnl_pct * p.trail_lock_frac
        target = (s.entry * (1 + kunci_pct / 100) if s.direction == "LONG"
                  else s.entry * (1 - kunci_pct / 100))
        lebih_baik = target > s.sl if s.direction == "LONG" else target < s.sl
        if lebih_baik:
            return ExitDecision(action="move_sl", reason="trail", new_sl=target,
                                note=f"kunci {p.trail_lock_frac:.0%} dari puncak "
                                     f"{s.peak_pnl_pct:.2f}%")

    # ── 4. Breakeven — SEBELUM TP1, dan hanya bila untungnya sudah bermakna ──
    if not s.tp1_done and not s.trail_active and breakeven_armed(s, p):
        be = protective_price(s, p)
        lebih_baik = be > s.sl if s.direction == "LONG" else be < s.sl
        if lebih_baik:
            return ExitDecision(action="move_sl", reason="breakeven", new_sl=be,
                                note=f"untung {_pnl_pct(s):.2f}% sudah > "
                                     f"{p.be_arm_cost_mult:.0f}x biaya ({s.cost_pct:.2f}%) "
                                     f"dan > {p.be_arm_atr}xATR")

    # ── 6. Time-stop — tesis tak jalan dalam jendela waktunya ────────────────
    if s.hold_minutes > p.max_hold_h * 60:
        progres = _pnl_pct(s) / s.risk_pct if s.risk_pct else 0.0
        if progres < p.time_stop_progress:
            return ExitDecision(action="close", reason=TIME_STOP, close_frac=1.0,
                                close_price=s.price,
                                note=f"tahan {s.hold_minutes/60:.1f} jam, progres "
                                     f"{progres:.2f}x risiko < {p.time_stop_progress}")

    return ExitDecision(action="hold", reason="hold")


def params_from_config() -> ExitParams:
    """Rakit dari `agent_config` (futures.exit_*)."""
    from agents.futures import exit_config as ecfg

    return ExitParams(
        tp1_atr_mult=ecfg.get("exit_tp1_atr_mult"),
        tp2_atr_mult=ecfg.get("exit_tp2_atr_mult"),
        tp1_close_frac=ecfg.get("exit_tp1_close_frac"),
        tp2_close_frac=ecfg.get("exit_tp2_close_frac"),
        be_arm_cost_mult=ecfg.get("exit_be_arm_cost_mult"),
        be_arm_atr=ecfg.get("exit_be_arm_atr"),
        be_lock_frac=ecfg.get("exit_be_lock_frac"),
        trail_lock_frac=ecfg.get("exit_trail_lock_frac"),
        max_hold_h=ecfg.get("exit_max_hold_h"),
        time_stop_progress=ecfg.get("exit_time_stop_progress"),
    )
