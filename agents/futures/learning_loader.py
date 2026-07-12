"""Muat bobot learning FUTURES + terapkan policy per-lane (F2).

Mirror pola agents/opportunity/scanner.py::_load_learning_weights + _apply_lane_learning
(engine SPOT tidak disentuh). Loader membaca agent_signal_weights yang sudah diisi
weight_updater trade-based (+ weekly review + predictive blend item C), lalu
apply_learning_policy menempelkan adaptive_score/probability/ban ke tiap kandidat.

Catatan cakupan (jujur, bukan bug): weight tersimpan futures memakai key legacy
normalize (bare). Policy meng-hasilkan `signal_id:*` canonical utk sinyal yang
punya rule F0, dan fallback `signal:<legacy>` utk sisanya. Maka bobot ter-apply
lewat jalur:
  - canonical: hanya bila ada baris DB ber-key canonical (belum ada sumbernya
    sampai fase learning canonical-keyed; sekarang neutral 1.0 — AMAN, veto-only),
  - fallback `signal:*`: bobot legacy untuk sinyal tanpa canonical ID.
Efek near-term pasca-reset (bobot mayoritas neutral) memang ~netral by design —
nilai F2 = wiring veto + probability + status + enrichment ledger/UI, BUKAN
mengubah rumus skor. Sumber weight canonical penuh = fase lanjutan.
"""

from __future__ import annotations

import time
from typing import Optional

import structlog

from agents.futures.learning_policy import apply_learning_policy

logger = structlog.get_logger(__name__)

_FUTURES_AGENTS = (
    "futures_agent1", "futures_agent2", "futures_agent3", "futures_agent_bigmover",
)
# Ambang kematangan ledger sebelum learning naik dari "warming" → "active"
# (identik gate F3/§4: 60 mature samples). Selama warming, HANYA hard-ban yang
# boleh mem-veto; veto lunak (adaptive_score turun) menunggu active.
MATURE_ACTIVE_THRESHOLD = 60
BAN_MIN_SAMPLES = 10          # mirror SPOT: ban butuh ≥10 sampel
BAN_WEIGHT_BELOW = 0.80


def _prefixed(key: str) -> str:
    """Ekspos bobot legacy di bawah namespace fallback policy (`signal:<key>`)."""
    return key if key.startswith(("signal:", "signal_id:", "lane:", "alert:")) else f"signal:{key}"


async def load_futures_learning() -> tuple[dict, dict, dict, set, str, Optional[str]]:
    """Returns (weights, probabilities, sample_counts, banned, status, error)."""
    try:
        from app.database import AsyncSessionLocal, is_db_available
        from app.models.signal_weight import AgentSignalWeight
        from app.models.futures_decision_event import FuturesDecisionEvent
        from sqlalchemy import select, func

        if not is_db_available():
            return {}, {}, {}, set(), "degraded", "database_unavailable"

        async with AsyncSessionLocal() as session:
            rows = list((await session.execute(
                select(AgentSignalWeight).where(
                    AgentSignalWeight.agent.in_([*_FUTURES_AGENTS, "cross_agent"]),
                    AgentSignalWeight.regime == "all",
                    AgentSignalWeight.total_count >= 3,
                )
            )).scalars().all())

            own = {r.signal_key: r for r in rows if r.agent != "cross_agent"}
            cross = {r.signal_key: r for r in rows if r.agent == "cross_agent"}

            weights: dict[str, float] = {}
            probabilities: dict[str, float] = {}
            sample_counts: dict[str, int] = {}
            for key in set(own) | set(cross):
                pkey = _prefixed(key)
                own_w = float(own[key].weight) if key in own else 1.0
                cross_w = float(cross[key].weight) if key in cross else 1.0
                weights[pkey] = round(own_w * 0.70 + cross_w * 0.30, 3)
                own_p = ((own[key].win_count + 1.0) / (own[key].total_count + 2.0)
                         if key in own else 0.5)
                cross_p = ((cross[key].win_count + 1.0) / (cross[key].total_count + 2.0)
                           if key in cross else 0.5)
                probabilities[pkey] = round(own_p * 0.70 + cross_p * 0.30, 4)
                sample_counts[pkey] = int(
                    own[key].total_count if key in own else cross[key].total_count
                )
            banned = {
                _prefixed(r.signal_key) for r in own.values()
                if r.weight < BAN_WEIGHT_BELOW and r.total_count >= BAN_MIN_SAMPLES
            }

            mature = int(await session.scalar(
                select(func.count(FuturesDecisionEvent.id)).where(
                    FuturesDecisionEvent.pnl_24h_pct.isnot(None)
                )
            ) or 0)

        status = "active" if mature >= MATURE_ACTIVE_THRESHOLD else "warming"
        return weights, probabilities, sample_counts, banned, status, None
    except Exception as exc:
        error = str(exc)[:120]
        logger.warning("futures_learning_weights_load_failed", error=error)
        return {}, {}, {}, set(), "degraded", error


def apply_lane_learning(
    rows: list[dict],
    weights: dict,
    probabilities: dict,
    sample_counts: dict,
    banned_keys: set,
    auto_threshold: float,
    learning_status: str,
) -> None:
    """Terapkan satu kontrak learning ke seluruh baris satu lane (in-place)."""
    for row in rows:
        apply_learning_policy(
            row, weights, banned_keys, auto_threshold,
            probabilities=probabilities, sample_counts=sample_counts,
        )
        row["learning_status"] = learning_status
