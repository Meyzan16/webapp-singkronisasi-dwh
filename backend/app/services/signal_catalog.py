"""
Signal Catalog — PLAN_v2 P3.3.

Maps normalized signal_key prefixes to human-readable metadata:
label, category, description, which agents use it, and max score contribution.

Kunci = ID stabil `signal_id:*`, sama persis dengan kunci bobot & scoring.
(Dulu kunci hasil `_normalize_signal` berbasis teks — lihat _LEGACY_ENTRIES.)
Since normalization strips numbers (→ N) and takes first 4 words, many TF-specific
variants collapse to the same key (e.g. "bb_squeeze_nh" covers 1H, 4H, etc.).

Usage:
    from app.services.signal_catalog import get_catalog_entry, SIGNAL_CATALOG
    entry = get_catalog_entry("bb_squeeze_nh")
"""

from __future__ import annotations

# Label agen dari registry tunggal (dulu salinan ke-3 di repo).
from app.services.agent_registry import AGENT_LABELS  # noqa: E402,F401

# Signal catalog — keyed by the normalized signal key (or prefix)
# Each entry: label, category, description, agents (list of agent+max_pts), score_formula
# Deskripsi tulisan-tangan. DULU ini adalah katalog itu sendiri, ber-kunci format
# LAMA (hasil normalisasi teks, mis. "bb_squeeze_nh"). Sejak identitas sinyal
# pindah ke ID stabil (`signal_id:tech.bb_squeeze`), kunci-kunci ini TIDAK PERNAH
# lagi cocok: audit 30 Jul 2026 menemukan 79 kunci sinyal aktif vs 17 entri
# katalog dengan irisan NOL — tab Formulas praktis yatim dan setiap pencarian
# label di UI jatuh ke kunci mentah.
# Sekarang perannya hanya PEMERKAYA deskripsi; katalog aslinya dibangun dinamis
# dari tabel aturan kedua market (lihat _build_catalog di bawah).
_LEGACY_ENTRIES: dict[str, dict] = {
    # ── Volatility / Squeeze ──────────────────────────────────────────────────
    "bb_squeeze_nh": {
        "label":       "BB Squeeze (TF)",
        "category":    "volatility",
        "description": "Bollinger Band width terkompresi multi-TF — energi menumpuk sebelum breakout besar.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer",  "max_pts": 35, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
            {"agent": "futures_agent2", "label": "Accumulation","max_pts": 18, "file": "agents/futures/agent2.py", "fn": "_score_accumulation"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0 per signal occurrence",
    },
    "bb_squeeze_nhm": {
        "label":       "BB Squeeze (15m)",
        "category":    "volatility",
        "description": "Bollinger Band squeeze di timeframe 15 menit — micro-coil sebelum breakout.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer",  "max_pts": 10, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    # ── Volume ────────────────────────────────────────────────────────────────
    "volume_akumulasi_n": {
        "label":       "Volume Accumulation",
        "category":    "volume",
        "description": "Volume naik signifikan sementara harga flat — smart money masuk diam-diam.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer",  "max_pts": 25, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
            {"agent": "futures_agent2", "label": "Accumulation","max_pts": 8,  "file": "agents/futures/agent2.py", "fn": "_score_accumulation"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    "volume_naik_n": {
        "label":       "Volume Rising",
        "category":    "volume",
        "description": "Volume naik dibandingkan rata-rata — konfirmasi momentum.",
        "agents": [
            {"agent": "futures_agent1",        "label": "Pre-Gainer",  "max_pts": 15, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
            {"agent": "futures_agent3",        "label": "Momentum",    "max_pts": 25, "file": "agents/futures/agent3.py", "fn": "_score_momentum_long"},
            {"agent": "futures_agent_bigmover","label": "BigMover",    "max_pts": 20, "file": "agents/futures/agent_bigmover.py", "fn": "_score_bigmover"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    "volume_distribusi_n": {
        "label":       "Volume Distribution",
        "category":    "volume",
        "description": "Volume naik di area tinggi sementara harga flat — smart money exit diam-diam.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer (SHORT)", "max_pts": 25, "file": "agents/futures/agent1.py", "fn": "_score_predump"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    # ── Funding Rate ──────────────────────────────────────────────────────────
    "funding_n_negatif": {
        "label":       "Funding Negatif",
        "category":    "funding",
        "description": "Funding rate negatif — shorts membayar longs, fuel untuk pump tersedia.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer",  "max_pts": 15, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
            {"agent": "futures_agent2", "label": "Accumulation","max_pts": 8,  "file": "agents/futures/agent2.py", "fn": "_score_accumulation"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    "funding_n_positif": {
        "label":       "Funding Positif Ekstrem",
        "category":    "funding",
        "description": "Funding rate tinggi — longs overcrowded, potensi liquidasi massal (bias SHORT).",
        "agents": [
            {"agent": "futures_agent1",        "label": "Pre-Gainer (SHORT)", "max_pts": 15, "file": "agents/futures/agent1.py",         "fn": "_score_predump"},
            {"agent": "futures_agent_bigmover","label": "BigMover",           "max_pts": 12, "file": "agents/futures/agent_bigmover.py", "fn": "_score_bigmover"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    # ── Open Interest ─────────────────────────────────────────────────────────
    "oi_n_posisi": {
        "label":       "OI Building",
        "category":    "open_interest",
        "description": "Open Interest naik — new money masuk, konviksi posisi meningkat.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer",  "max_pts": 12, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
            {"agent": "futures_agent2", "label": "Accumulation","max_pts": 8,  "file": "agents/futures/agent2.py", "fn": "_score_accumulation"},
            {"agent": "futures_agent3", "label": "Momentum",    "max_pts": 8,  "file": "agents/futures/agent3.py", "fn": "_score_momentum_long"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    # ── RSI ───────────────────────────────────────────────────────────────────
    "rsi_n_sweet": {
        "label":       "RSI Sweet Spot",
        "category":    "momentum",
        "description": "RSI di zona ideal — momentum baru terbentuk, belum overbought.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer",  "max_pts": 12, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
            {"agent": "futures_agent2", "label": "Accumulation","max_pts": 13, "file": "agents/futures/agent2.py", "fn": "_score_accumulation"},
            {"agent": "futures_agent3", "label": "Momentum",    "max_pts": 12, "file": "agents/futures/agent3.py", "fn": "_score_momentum_long"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    "rsi_n_recovering": {
        "label":       "RSI Recovering",
        "category":    "momentum",
        "description": "RSI recovering dari oversold — reversal bias bullish.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer", "max_pts": 8, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    # ── Structure / S&R ───────────────────────────────────────────────────────
    "dekat_resistance_n": {
        "label":       "Near Resistance",
        "category":    "structure",
        "description": "Harga dekat level resistance — catalyst breakout dalam jangkauan.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer",  "max_pts": 15, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
            {"agent": "futures_agent2", "label": "Accumulation","max_pts": 14, "file": "agents/futures/agent2.py", "fn": "_score_accumulation"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    "di_zona_resistance": {
        "label":       "At Resistance Zone",
        "category":    "structure",
        "description": "Harga di zona resistance — area penolakan, bias SHORT.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer (SHORT)", "max_pts": 15, "file": "agents/futures/agent1.py", "fn": "_score_predump"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    # ── Flat coin bonus ───────────────────────────────────────────────────────
    "flat_n_bb": {
        "label":       "Flat + BB Squeeze",
        "category":    "composite",
        "description": "Harga flat ±2% 24h + BB squeeze — sidik jari sempurna pre-gainer sebelum ledakan.",
        "agents": [
            {"agent": "futures_agent1", "label": "Pre-Gainer", "max_pts": 8, "file": "agents/futures/agent1.py", "fn": "_score_pregainer"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    # ── BigMover ──────────────────────────────────────────────────────────────
    "magnitude_bonus_n": {
        "label":       "Move Magnitude Bonus",
        "category":    "magnitude",
        "description": "Bonus untuk besar pergerakan 24h — makin besar momentum, makin tinggi skor BigMover.",
        "agents": [
            {"agent": "futures_agent_bigmover", "label": "BigMover", "max_pts": 30, "file": "agents/futures/agent_bigmover.py", "fn": "_score_bigmover"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    # ── Momentum (agent3) ─────────────────────────────────────────────────────
    "breakout_n_candle": {
        "label":       "30-Candle Breakout",
        "category":    "breakout",
        "description": "Harga menembus high/low 30 candle terakhir — konfirmasi momentum breakout.",
        "agents": [
            {"agent": "futures_agent3", "label": "Momentum", "max_pts": 25, "file": "agents/futures/agent3.py", "fn": "_score_momentum_long"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    # ── Wyckoff ───────────────────────────────────────────────────────────────
    "wyckoff_accumulation": {
        "label":       "Wyckoff Accumulation",
        "category":    "wyckoff",
        "description": "Phase Wyckoff accumulation terdeteksi — pre-markup, smart money sedang masuk.",
        "agents": [
            {"agent": "futures_agent2", "label": "Accumulation", "max_pts": 20, "file": "agents/futures/agent2.py", "fn": "_score_accumulation"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
    "wyckoff_distribution": {
        "label":       "Wyckoff Distribution",
        "category":    "wyckoff",
        "description": "Phase Wyckoff distribution terdeteksi — pre-markdown, smart money sedang keluar.",
        "agents": [
            {"agent": "futures_agent2", "label": "Accumulation (SHORT)", "max_pts": 20, "file": "agents/futures/agent2.py", "fn": "_score_distribution"},
        ],
        "score_impact_formula": "(weight − 1.0) × 7.0",
    },
}

# ── Katalog dinamis ───────────────────────────────────────────────────────────
# Dibangun dari tabel aturan canonical KEDUA market, jadi setiap sinyal yang
# benar-benar bisa muncul otomatis punya entri — termasuk sinyal yang lahir
# nanti. Tak ada lagi daftar yang harus disunting manual dan bisa ketinggalan.

_CATEGORY_BY_PREFIX = {
    "tech":     "teknikal",
    "flow":     "aliran dana",
    "momentum": "momentum",
    "mom":      "momentum",
    "bm":       "big mover",
    "fund":     "funding",
    "wyckoff":  "wyckoff",
    "oi":       "open interest",
}


def _humanize(stable_id: str) -> str:
    """'tech.bb_squeeze' -> 'BB Squeeze'; dipakai bila tak ada label manual."""
    tail = stable_id.split(".", 1)[-1]
    words = tail.replace("_", " ").split()
    out = []
    for w in words:
        out.append(w.upper() if len(w) <= 3 and w.isalpha() else w.capitalize())
    return " ".join(out)


def _legacy_description_map() -> dict[str, dict]:
    """Petakan deskripsi lama (ber-kunci teks) ke ID stabil.

    Kunci lama adalah hasil normalisasi teks, jadi kata-katanya masih utuh —
    cukup dijalankan lewat pencocok aturan untuk menemukan ID canonical-nya.
    """
    from agents.futures.learning_policy import canonical_signal_key as fut_ck
    from agents.opportunity.learning_policy import canonical_signal_key as spot_ck

    mapped: dict[str, dict] = {}
    for old_key, entry in _LEGACY_ENTRIES.items():
        text = old_key.replace("_", " ")
        sid = fut_ck(text) or spot_ck(text)
        if sid:
            mapped.setdefault(sid, entry)
    return mapped


def _build_catalog() -> dict[str, dict]:
    from agents.futures.learning_policy import _SIGNAL_ID_RULES as FUT_RULES
    from agents.opportunity.learning_policy import _SIGNAL_ID_RULES as SPOT_RULES

    desc = _legacy_description_map()
    out: dict[str, dict] = {}

    for rules, market in ((FUT_RULES, "futures"), (SPOT_RULES, "spot")):
        for required_parts, stable_id in rules:
            key = f"signal_id:{stable_id}"
            entry = out.get(key)
            if entry is None:
                legacy = desc.get(key, {})
                entry = {
                    "label":       legacy.get("label") or _humanize(stable_id),
                    "category":    legacy.get("category")
                                   or _CATEGORY_BY_PREFIX.get(stable_id.split(".")[0], "lainnya"),
                    "description": legacy.get("description", ""),
                    "agents":      legacy.get("agents", []),
                    "score_impact_formula": legacy.get(
                        "score_impact_formula", "(weight − 1.0) × 7.0 per kemunculan"),
                    # Pemetaan market — inilah yang membuat Formulas bisa
                    # menjawab "sinyal ini dipakai SPOT, FUTURES, atau keduanya".
                    "markets":     [],
                    "match_terms": [],
                }
                out[key] = entry
            if market not in entry["markets"]:
                entry["markets"].append(market)
            entry["match_terms"].append(" + ".join(required_parts))
    return out


#: Katalog aktif — ber-kunci ID stabil, sama dengan kunci bobot & scoring.
SIGNAL_CATALOG: dict[str, dict] = _build_catalog()

# Peta balik: agen → sinyal yang dipakainya. Dibangun SETELAH katalog ada
# (dulu di atas, merujuk katalog sebelum terdefinisi).
AGENT_SIGNAL_MAP: dict[str, list[str]] = {}
for _sig_key, _entry in SIGNAL_CATALOG.items():
    for _ag in _entry.get("agents", []):
        AGENT_SIGNAL_MAP.setdefault(_ag["agent"], []).append(_sig_key)


def get_catalog_entry(signal_key: str) -> dict | None:
    """Metadata untuk sebuah kunci sinyal (ID stabil `signal_id:*`).

    Kunci fallback berbasis teks (`signal:*`) sengaja TIDAK dicocokkan paksa —
    lebih baik mengembalikan None daripada menautkan penjelasan sinyal yang salah.
    """
    return SIGNAL_CATALOG.get(signal_key)


def get_all_categories() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for e in SIGNAL_CATALOG.values():
        c = e.get("category", "lainnya")
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out
