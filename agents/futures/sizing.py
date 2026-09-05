"""Mesin ukuran FUTURES — satu rumus, dan ia menjelaskan dirinya sendiri.

PLAN-FUTURES-AGENTIC.md Fase 2. Menggantikan rantai keputusan yang sebelumnya
tersebar di `balance.compute_futures_sizing` + `utils.cap_leverage_by_lane` +
enam pengali di `auto_trader`.

── Kenapa ada ────────────────────────────────────────────────────────────────
Terukur 5 Sep 2026 pada 112 trade: risiko per trade median **$4,98** padahal
aturannya 1% dari wallet $854 = $8,54. Selisihnya bukan bug tunggal melainkan
enam pengali yang dikalikan bertumpuk — probe x1/2, profit-lock x1/2, weekend
x1/2, funding-soft x1/2, lane-throttle x1/2, dan lane bigmover yang memang mulai
dari setengah risiko. Hasilnya bisa turun sampai 1/32 tanpa satu pun angka yang
"memutuskan" ukurannya, dan tanpa satu pun tempat yang bisa ditanya kenapa.

Modul ini menggantinya dengan SATU pengali (`tier_mult`) dan mengembalikan objek
yang memuat setiap angka antara — sehingga pertanyaan "kenapa posisi ini
segini?" selalu punya jawaban yang bisa dibaca manusia, tersimpan di
`paper_trades.sizing_json`, dan bisa dipelajari mesin.

── Rumusnya ─────────────────────────────────────────────────────────────────
    1. risk_usd  = balance x risk_pct x tier_mult
    2. notional  = risk_usd / sl_pct
    3. leverage  = clamp(margin_loss_at_sl_pct / sl_pct, lev_min, lev_max)
                   lalu dibatasi (95 / liq_safety) / sl_pct
    4. margin    = notional / leverage,  dibatasi max_margin_frac x balance
    5. notional  dibatasi max_notional_mult x balance
    6. gerbang   laba, dolar, slot, notional minimum

Sifat yang dijaga rumus ini: **rugi saat SL selalu ~= risk_usd, berapa pun
SL-nya.** Leverage adalah AKIBAT dari jarak SL (supaya rugi margin di SL selalu
sekitar `margin_loss_at_sl_pct`), bukan angka tetap per lane. Itulah arti
"kerugian terukur": satu angka yang sama untuk semua koin.

Fungsi ini MURNI — tak menyentuh DB, tak async, tak membaca jam. Semua masukan
eksplisit. Pemanggil yang mengambil balance/posisi terbuka dari DB.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SizingParams:
    """Parameter rumus. Diisi dari `agent_config` lewat `params_from_config()`."""

    risk_pct: float                  # % wallet berisiko per trade (K1)
    margin_loss_at_sl_pct: float     # target rugi margin saat SL kena (K3)
    lev_min: float
    lev_max: float                   # (K4)
    liq_safety_mult: float
    max_margin_frac: float
    max_notional_mult: float
    min_notional_abs: float
    min_profit_usd: float            # TP1 bersih minimum agar kandidat boleh masuk (K5)
    min_profit_cost_mult: float
    max_positions: int               # (K2)
    portfolio_max_risk_pct: float


@dataclass(frozen=True)
class SizingResult:
    """Hasil + SELURUH angka antara. `reason` selalu terisi, juga saat lolos."""

    can_open: bool
    reason: str
    risk_usd: float
    notional: float
    leverage: int
    margin: float
    cost_usd: float
    tp1_net_usd: float
    sl_net_usd: float
    profit_to_cost: float
    tier_mult: float
    # Konteks — supaya baris ledger bisa dibaca tanpa menebak keadaan saat itu.
    balance: float
    available: float
    open_positions: int
    open_risk_usd: float
    sl_pct: float
    tp1_pct: float

    def as_dict(self) -> dict:
        return asdict(self)


def params_from_config() -> SizingParams:
    """Rakit parameter dari `sizing_config` (yang membacanya dari `agent_config`).

    Dipisah dari `compute()` supaya rumusnya tetap murni dan bisa diuji dengan
    angka buatan tanpa menyentuh config sama sekali.
    """
    from agents.futures import sizing_config as szcfg

    return SizingParams(
        risk_pct=szcfg.get("size_risk_base_pct"),
        margin_loss_at_sl_pct=szcfg.get("size_margin_loss_at_sl_pct"),
        lev_min=szcfg.get("lev_min"),
        lev_max=szcfg.get("lev_max"),
        liq_safety_mult=szcfg.get("lev_liq_safety_mult"),
        max_margin_frac=szcfg.max_margin_fraction(),
        max_notional_mult=szcfg.get("size_max_notional_mult"),
        min_notional_abs=szcfg.get("size_min_notional_abs"),
        min_profit_usd=szcfg.get("size_min_profit_usd"),
        min_profit_cost_mult=szcfg.get("size_min_profit_cost_mult"),
        max_positions=int(szcfg.get("max_auto_positions")),
        portfolio_max_risk_pct=szcfg.get("size_portfolio_max_risk_pct"),
    )


def leverage_for_sl(sl_pct: float, p: SizingParams) -> int:
    """Leverage yang membuat rugi margin saat SL ~= `margin_loss_at_sl_pct`.

    Dibatasi dua hal, yang terkecil menang:
      * rentang operator `lev_min..lev_max`;
      * keselamatan likuidasi — jarak likuidasi (~95/lev pada MMR 1%) harus
        minimal `liq_safety_mult` kali jarak SL, supaya wick yang menyentuh SL
        tak pernah mendarat di zona likuidasi.
    """
    if sl_pct <= 0:
        return max(1, int(p.lev_min))
    ideal = p.margin_loss_at_sl_pct / sl_pct
    liq_cap = (95.0 / p.liq_safety_mult) / sl_pct
    return max(1, int(min(max(ideal, p.lev_min), p.lev_max, liq_cap)))


def compute(
    *,
    balance: float,
    sl_pct: float,
    tp1_pct: float,
    cost_pct: float,
    p: SizingParams,
    open_positions: int = 0,
    open_risk_usd: float = 0.0,
    locked_margin: float = 0.0,
    tier_mult: float = 1.0,
    min_notional_exchange: float = 0.0,
    enforce_profit_gates: bool = True,
) -> SizingResult:
    """Hitung ukuran satu kandidat.

    `enforce_profit_gates=False` menghitung dan MELAPORKAN gerbang laba tanpa
    memakainya untuk menolak — dipakai jalur lama (4 lane) selama masa transisi,
    supaya Fase 2 tak diam-diam mengubah kandidat mana yang lolos.
    """
    available = balance - locked_margin

    def gagal(reason: str, **kw) -> SizingResult:
        return _build(reason=reason, can_open=False, balance=balance, available=available,
                      open_positions=open_positions, open_risk_usd=open_risk_usd,
                      sl_pct=sl_pct, tp1_pct=tp1_pct, tier_mult=tier_mult, **kw)

    if balance <= 0:
        return gagal("wallet kosong")
    if sl_pct <= 0:
        return gagal("jarak SL tidak valid (<= 0)")

    # 1-2. Risiko lalu notional. SATU pengali, bukan tumpukan.
    risk_usd = balance * (p.risk_pct / 100.0) * max(0.0, tier_mult)
    notional = risk_usd / (sl_pct / 100.0)

    # 3. Leverage sebagai AKIBAT dari jarak SL.
    leverage = leverage_for_sl(sl_pct, p)

    # 5. Plafon notional terhadap wallet (BUG-L4: SL sempit bisa meniup ukuran).
    max_notional = balance * p.max_notional_mult
    if notional > max_notional:
        notional = max_notional
        risk_usd = notional * (sl_pct / 100.0)

    # 4. Margin + plafonnya. Menurunkan margin berarti menurunkan notional —
    #    leverage TIDAK dinaikkan diam-diam untuk mengejar ukuran, karena itu
    #    akan menggeser jarak likuidasi yang sudah dijamin di langkah 3.
    margin = notional / leverage
    max_margin = balance * p.max_margin_frac
    if margin > max_margin:
        margin = max_margin
        notional = margin * leverage
        risk_usd = notional * (sl_pct / 100.0)

    # Biaya & hasil dalam DOLAR — inti "terukur".
    cost_usd = notional * (cost_pct / 100.0)
    tp1_net_usd = notional * (tp1_pct / 100.0) - cost_usd
    sl_net_usd = -(risk_usd + cost_usd)
    profit_to_cost = (tp1_net_usd / cost_usd) if cost_usd > 0 else 0.0

    hasil = dict(risk_usd=risk_usd, notional=notional, leverage=leverage, margin=margin,
                 cost_usd=cost_usd, tp1_net_usd=tp1_net_usd, sl_net_usd=sl_net_usd,
                 profit_to_cost=profit_to_cost)

    # 6. Gerbang — paling mengikat lebih dulu, supaya alasannya paling berguna.
    if open_positions >= p.max_positions:
        return gagal(f"slot penuh: {open_positions}/{p.max_positions} posisi terbuka", **hasil)

    heat_cap = balance * (p.portfolio_max_risk_pct / 100.0)
    if open_risk_usd + risk_usd > heat_cap:
        return gagal(
            f"panas portofolio: risiko terbuka ${open_risk_usd:,.2f} + ${risk_usd:,.2f} "
            f"> {p.portfolio_max_risk_pct:.0f}% wallet (${heat_cap:,.2f})", **hasil)

    if margin > available:
        return gagal(f"margin ${margin:,.2f} > dana bebas ${available:,.2f}", **hasil)

    if notional < max(p.min_notional_abs, min_notional_exchange):
        return gagal(
            f"notional ${notional:,.2f} < minimum "
            f"${max(p.min_notional_abs, min_notional_exchange):,.2f} (anti-debu)", **hasil)

    if enforce_profit_gates:
        # Gerbang laba: TP1 harus mengalahkan biaya beberapa kali lipat. Tanpa
        # ini, posisi dibuka untuk peluang yang menang pun hanya sebesar fee —
        # 31 trade `sl_plus` rata-rata +$0,30 adalah bukti langsungnya.
        if tp1_pct < p.min_profit_cost_mult * cost_pct:
            return gagal(
                f"TP1 {tp1_pct:.2f}% < {p.min_profit_cost_mult:.0f}x biaya "
                f"({cost_pct:.2f}%) — menang pun cuma menutup fee", **hasil)
        # Gerbang dolar: sekali menang harus berarti dalam uang, bukan hanya
        # dalam persen. Inilah yang mencegah "masuk cuma 3 dolar".
        if tp1_net_usd < p.min_profit_usd:
            return gagal(
                f"TP1 bersih ${tp1_net_usd:,.2f} < minimum ${p.min_profit_usd:,.2f}", **hasil)

    return _build(reason="ok", can_open=True, balance=balance, available=available,
                  open_positions=open_positions, open_risk_usd=open_risk_usd,
                  sl_pct=sl_pct, tp1_pct=tp1_pct, tier_mult=tier_mult, **hasil)


def _build(**kw) -> SizingResult:
    """Isi field yang tak terhitung dengan 0 lalu bulatkan — supaya setiap jalur
    keluar mengembalikan bentuk yang SAMA. Hasil dengan field hilang akan
    memaksa pemanggil menebak, dan tebakan itulah yang jadi bug berikutnya."""
    dasar = dict(risk_usd=0.0, notional=0.0, leverage=0, margin=0.0, cost_usd=0.0,
                 tp1_net_usd=0.0, sl_net_usd=0.0, profit_to_cost=0.0)
    dasar.update(kw)
    for k in ("risk_usd", "notional", "margin", "cost_usd", "tp1_net_usd",
              "sl_net_usd", "balance", "available", "open_risk_usd"):
        dasar[k] = round(float(dasar[k]), 2)
    dasar["profit_to_cost"] = round(float(dasar["profit_to_cost"]), 2)
    dasar["leverage"] = int(dasar["leverage"])
    return SizingResult(**dasar)


def explain(r: SizingResult) -> str:
    """Satu kalimat yang menjelaskan posisi — untuk log, Telegram, dan UI."""
    if not r.can_open:
        return f"DITOLAK: {r.reason}"
    return (
        f"risiko ${r.risk_usd:,.2f} pada SL {r.sl_pct:.2f}% -> notional "
        f"${r.notional:,.2f} @ {r.leverage}x (margin ${r.margin:,.2f}); "
        f"TP1 memberi +${r.tp1_net_usd:,.2f} bersih, SL memakan ${abs(r.sl_net_usd):,.2f}, "
        f"biaya ${r.cost_usd:,.2f} (untung:biaya {r.profit_to_cost:.1f}x)"
    )
