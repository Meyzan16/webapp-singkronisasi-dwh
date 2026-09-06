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

#: SEMUA agen futures yang pernah ada — dipakai untuk QUERY RIWAYAT (posisi
#: terbuka, trade tertutup, bobot, ledger). Turunan langsung dari layer agent.
#:
#: Namanya tetap `FUTURES_AGENTS` DENGAN SENGAJA: ~30 tempat sudah mengimpornya
#: dan semuanya memang bertanya soal riwayat. Mengganti artinya diam-diam akan
#: membuat 112 trade lama hilang dari laporan, saldo, dan gerbang risiko tanpa
#: satu pun error — jenis kegagalan senyap yang sudah dua kali memakan waktu
#: proyek ini (30 Jul: BigMover hilang dari Signal Performance; 29 Jul: bobot
#: repair tak beririsan).
FUTURES_AGENTS: list[str] = list(_FUTURES_AGENTS)

#: Agen yang BOLEH MEMINDAI dan membuka posisi baru. Sejak Fase 3 satu.
#: Pakai daftar ini HANYA untuk pertanyaan "siapa yang bertindak sekarang".
ACTIVE_FUTURES_AGENTS: list[str] = ["futures_agentic"]

#: Agen yang sudah pensiun: tak memindai lagi, tapi riwayatnya wajib terbaca.
#: Dihapus di Fase 8, setelah posisi terbuka terakhirnya tutup.
LEGACY_FUTURES_AGENTS: list[str] = [
    a for a in FUTURES_AGENTS if a not in ACTIVE_FUTURES_AGENTS
]

#: Alias eksplisit untuk pemanggil yang ingin niatnya terbaca di tempat.
ALL_FUTURES_AGENTS: list[str] = FUTURES_AGENTS

#: Agen yang benar-benar men-trade (punya paper_trades sendiri).
#: Memuat yang pensiun juga — dipakai laporan & agregasi riwayat.
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
    "futures_agentic":        "Agentic",
    CROSS_AGENT:              "Cross-Agent",
}

#: Nama pendek untuk tabel/badge sempit.
AGENT_SHORT: dict[str, str] = {
    SPOT_AGENT:               "SPOT",
    "futures_agent1":         "Pre",
    "futures_agent2":         "Accum",
    "futures_agent3":         "Momo",
    "futures_agent_bigmover": "BigMover",
    "futures_agentic":        "Agentic",
    CROSS_AGENT:              "Cross",
}


#: Agen futures → nama lane di risk-gate / quota. Dipakai untuk membaca status
#: pause & win-rate per lane. Sempat ditulis ulang di `_RECO_CATEGORIES`
#: (signals.py) dan `lane_map` (endpoint agent_health) — dua salinan yang harus
#: dijaga sinkron manual. Sekarang satu sumber.
AGENT_LANE: dict[str, str] = {
    "futures_agent1":         "pre_gainer",
    "futures_agent2":         "accumulation",
    "futures_agent3":         "momentum",
    "futures_agent_bigmover": "bigmover",
    "futures_agentic":        "agentic",
}

#: Kebalikannya: lane → agen.
LANE_AGENT: dict[str, str] = {lane: agent for agent, lane in AGENT_LANE.items()}

#: Lane milik agen PENSIUN. Dipakai generator config per-lane lama
#: (`sl_config`, `monitor_config`), yang memang hanya melayani jalur monitor lama.
#:
#: Lane `agentic` SENGAJA tidak di sini: seluruh parameter keluarnya datang dari
#: `exit_config` (satu set, bukan per lane). Memberinya baris per-lane akan
#: menghidupkan kembali persis yang sedang ditinggalkan Fase 4 — 38 konstanta
#: monitor plus 21 kunci per lane untuk pertanyaan yang sama.
LEGACY_LANES: list[str] = sorted(
    lane for agent, lane in AGENT_LANE.items() if agent in LEGACY_FUTURES_AGENTS
)


def agent_market(agent: str) -> str:
    """"spot" | "futures" — dipakai UI/laporan untuk mengelompokkan per market."""
    return "futures" if agent.startswith("futures_") else "spot"


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
