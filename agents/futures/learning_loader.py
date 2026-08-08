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

# PLAN_SIGNAL_REPAIR_LIVE R1: deteksi transisi ban/unban antar-load supaya
# perubahan status ban tercatat di repair ledger (bukan senyap).
_prev_banned: set | None = None
# Ambang kematangan ledger sebelum learning naik dari "warming" → "active"
# (identik gate F3/§4: 60 mature samples). Selama warming, HANYA hard-ban yang
# boleh mem-veto; veto lunak (adaptive_score turun) menunggu active.
MATURE_ACTIVE_THRESHOLD = 60
BAN_MIN_SAMPLES = 10          # mirror SPOT: ban butuh ≥10 sampel
BAN_WEIGHT_BELOW = 0.80


from dataclasses import dataclass


@dataclass(frozen=True)
class _Agg:
    """Gabungan beberapa baris bobot untuk SATU kunci sinyal.

    Dipakai agar kunci yang dimiliki lebih dari satu lane tidak saling menimpa.
    Fieldnya sengaja bernama sama dengan kolom `AgentSignalWeight` supaya kode di
    bawahnya membacanya tanpa perlu tahu ini hasil gabungan atau baris tunggal.
    """

    weight: float
    win_count: int
    total_count: int


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

            # Kontrak bobot ini SATU untuk semua lane (lihat pemanggil di
            # scheduler: `_lw` yang sama diterapkan ke agent1/2/3/bigmover).
            #
            # Dulu barisnya dipetakan `{r.signal_key: r}` — dikunci HANYA oleh
            # signal_key. Saat dua lane punya kunci yang sama, satu baris menimpa
            # yang lain dan pemenangnya ditentukan URUTAN BARIS dari database,
            # bukan bukti. Terukur 8 Agu 2026: `signal_id:flow.volume_momentum`
            # dimiliki agent3 (w=0,848 n=14) DAN bigmover (w=0,829 n=15); satu di
            # antaranya hilang tanpa jejak, dan hasilnya bisa berubah antar restart.
            #
            # Sekarang baris yang bertabrakan DIGABUNG dengan bobot sebanding
            # jumlah sampelnya — deterministik, dan tak ada bukti yang dibuang.
            def _merge(items: list) -> dict:
                grouped: dict[str, list] = {}
                for row in items:
                    grouped.setdefault(row.signal_key, []).append(row)
                out: dict[str, _Agg] = {}
                for key, group in grouped.items():
                    total = sum(g.total_count for g in group) or 1
                    out[key] = _Agg(
                        weight=sum(g.weight * g.total_count for g in group) / total,
                        win_count=sum(g.win_count for g in group),
                        total_count=sum(g.total_count for g in group),
                    )
                return out

            own = _merge([r for r in rows if r.agent != "cross_agent"])
            cross = _merge([r for r in rows if r.agent == "cross_agent"])

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
            # `own` kini memetakan kunci → agregat, jadi kuncinya diambil dari
            # item, bukan dari atribut baris ORM yang sudah tidak ada di sini.
            banned = {
                _prefixed(key) for key, agg in own.items()
                if agg.weight < BAN_WEIGHT_BELOW and agg.total_count >= BAN_MIN_SAMPLES
            }

            mature = int(await session.scalar(
                select(func.count(FuturesDecisionEvent.id)).where(
                    FuturesDecisionEvent.pnl_24h_pct.isnot(None)
                )
            ) or 0)

        status = "active" if mature >= MATURE_ACTIVE_THRESHOLD else "warming"

        # R1: catat transisi ban/unban (sekali per transisi, bukan per load)
        global _prev_banned
        if _prev_banned is not None and banned != _prev_banned:
            try:
                from agents.futures.repair_log import record_action
                for key in sorted(banned - _prev_banned):
                    await record_action(
                        source="learning_ban", target_key=key, issue="weight_ban",
                        action="ban", evidence={"threshold": BAN_WEIGHT_BELOW,
                                                "min_samples": BAN_MIN_SAMPLES},
                        note="weight<0.8 n≥10 → veto auto-open",
                    )
                for key in sorted(_prev_banned - banned):
                    await record_action(
                        source="learning_ban", target_key=key, issue="weight_unban",
                        action="unban", evidence={},
                        note="bobot pulih ≥0.8 → veto dicabut",
                    )
            except Exception as exc:
                logger.warning("ban_transition_log_failed", error=str(exc)[:120])
        _prev_banned = set(banned)

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
