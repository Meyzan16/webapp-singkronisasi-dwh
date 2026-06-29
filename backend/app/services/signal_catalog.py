"""
Signal Catalog — PLAN_v2 P3.3.

Maps normalized signal_key prefixes to human-readable metadata:
label, category, description, which agents use it, and max score contribution.

Keys match the output of agents.futures.weight_updater._normalize_signal().
Since normalization strips numbers (→ N) and takes first 4 words, many TF-specific
variants collapse to the same key (e.g. "bb_squeeze_nh" covers 1H, 4H, etc.).

Usage:
    from app.services.signal_catalog import get_catalog_entry, SIGNAL_CATALOG
    entry = get_catalog_entry("bb_squeeze_nh")
"""

from __future__ import annotations

AGENT_LABELS = {
    "futures_agent1":        "Pre-Gainer",
    "futures_agent2":        "Accumulation",
    "futures_agent3":        "Momentum",
    "futures_agent_bigmover":"BigMover",
    "opportunity_spot":      "SPOT",
    "cross_agent":           "Cross-Agent",
}

# Signal catalog — keyed by the normalized signal key (or prefix)
# Each entry: label, category, description, agents (list of agent+max_pts), score_formula
SIGNAL_CATALOG: dict[str, dict] = {
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

# Reverse map: agent → list of signal keys used
AGENT_SIGNAL_MAP: dict[str, list[str]] = {}
for _sig_key, _entry in SIGNAL_CATALOG.items():
    for _ag in _entry.get("agents", []):
        AGENT_SIGNAL_MAP.setdefault(_ag["agent"], []).append(_sig_key)


def get_catalog_entry(signal_key: str) -> dict | None:
    """Return catalog metadata for a normalized signal key.

    Tries exact match first, then prefix match (first 3 underscore segments).
    """
    if signal_key in SIGNAL_CATALOG:
        return SIGNAL_CATALOG[signal_key]
    # Prefix match — e.g. "bb_squeeze_nh_nn%" → prefix "bb_squeeze_nh"
    prefix = "_".join(signal_key.split("_")[:3])
    return SIGNAL_CATALOG.get(prefix)


def get_all_categories() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for e in SIGNAL_CATALOG.values():
        c = e.get("category", "other")
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out
