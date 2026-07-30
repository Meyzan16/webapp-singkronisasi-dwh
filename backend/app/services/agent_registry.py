"""Registry agen — SATU sumber kebenaran untuk "agen apa saja yang ada".

Masalah yang diselesaikan (audit 30 Jul 2026): daftar agen disalin ulang di
belasan tempat (API, UI, diagnostik). Saat lane `futures_agent_bigmover` lahir
(Phase 2 BM1), sebagian daftar ikut diperbarui dan sebagian TIDAK — akibatnya
`ALL_AGENTS` di `api/v1/signals.py` membuang lane itu dari SELURUH Signal
Performance tanpa satu pun error: 14 sinyal yang memenuhi ambang tak pernah
tampil. Kegagalan model ini SENYAP, jadi mahal untuk ditemukan.

Aturan pakai: JANGAN menulis literal daftar agen di file lain. Impor dari sini.
Daftar futures sendiri bersumber dari `agents.futures.weight_updater.FUTURES_AGENTS`
supaya lane baru cukup didaftarkan SEKALI di layer agent.
"""

from __future__ import annotations

# Sumber kebenaran lane futures ada di layer agent (dipakai scoring & learning).
from agents.futures.weight_updater import FUTURES_AGENTS as _FUTURES_AGENTS

SPOT_AGENT = "opportunity_spot"
CROSS_AGENT = "cross_agent"

#: Lane futures — turunan langsung dari layer agent, bukan salinan.
FUTURES_AGENTS: list[str] = list(_FUTURES_AGENTS)

#: Agen yang benar-benar men-trade (punya paper_trades sendiri).
TRADING_AGENTS: list[str] = [SPOT_AGENT] + FUTURES_AGENTS

#: Semua agen termasuk `cross_agent` (turunan/blending, bukan penerbit trade).
ALL_AGENTS: list[str] = TRADING_AGENTS + [CROSS_AGENT]

#: Nama panjang untuk UI/laporan.
AGENT_LABELS: dict[str, str] = {
    SPOT_AGENT:               "SPOT",
    "futures_agent1":         "Pre-Gainer",
    "futures_agent2":         "Accumulation",
    "futures_agent3":         "Momentum",
    "futures_agent_bigmover": "BigMover",
    CROSS_AGENT:              "Cross-Agent",
}

#: Nama pendek untuk tabel/badge sempit.
AGENT_SHORT: dict[str, str] = {
    SPOT_AGENT:               "SPOT",
    "futures_agent1":         "Pre",
    "futures_agent2":         "Accum",
    "futures_agent3":         "Momo",
    "futures_agent_bigmover": "BigMover",
    CROSS_AGENT:              "Cross",
}


def is_futures_agent(agent: str) -> bool:
    """Berbasis prefix supaya lane baru ikut terhitung walau belum diberi label."""
    return agent.startswith("futures_")


def agent_label(agent: str) -> str:
    """Label ramah-baca; jatuh ke kunci mentah bila lane belum dikatalogkan
    (lebih baik menampilkan kunci apa adanya daripada salah menamai lane lain)."""
    return AGENT_LABELS.get(agent, agent)


def agent_short(agent: str) -> str:
    """Label pendek; fallback membuang prefix `futures_agent` agar tetap terbaca."""
    if agent in AGENT_SHORT:
        return AGENT_SHORT[agent]
    return agent.replace("futures_agent_", "").replace("futures_agent", "A") or agent
