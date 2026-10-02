"""GET /futures/shadow-report — hasil riset sinyal shadow futures untuk FE.

Read-only. Logika & aturan lulus ada di agents/futures/shadow_report.py (satu
sumber dengan skrip ops/shadow_report.py dan laporan Telegram).
"""

import time

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database import is_db_available

router = APIRouter(tags=["futures"])
logger = structlog.get_logger(__name__)

_CACHE_TTL = 120.0
_cache: tuple[float, "ShadowReportResponse"] | None = None


class ShadowStats(BaseModel):
    """Statistik bracket satu kelompok sinyal."""
    n: int
    r_per_trade: float | None
    tp_rate: float | None
    profit_factor: float | None
    median_hold_min: float | None


class ShadowCheck(BaseModel):
    """Satu aturan lulus beserta nilai sekarang."""
    rule: str
    ok: bool
    value: str


class ShadowGroup(BaseModel):
    """Hasil satu hipotesis + arah."""
    hypothesis: str
    direction: str
    description: str
    pending: int
    is_control: bool
    all: ShadowStats
    first_half: ShadowStats
    second_half: ShadowStats
    checks: list[ShadowCheck] = []
    passed: bool = False
    edge_vs_control: float | None = None


class ShadowReportResponse(BaseModel):
    """Ringkasan riset shadow."""
    started_at: float | None
    labelled: int
    pending: int
    control_r_per_trade: float
    rules: dict[str, float]
    groups: list[ShadowGroup]
    generated_at: float


@router.get("/futures/shadow-report", response_model=ShadowReportResponse)
async def shadow_report() -> ShadowReportResponse:
    """Ringkasan riset shadow (cache 2 menit — label baru masuk tiap ±20 menit)."""
    global _cache
    now = time.time()
    if _cache and now - _cache[0] < _CACHE_TTL:
        return _cache[1]
    if not is_db_available():
        raise HTTPException(status_code=503, detail="database tidak tersedia")
    from agents.futures.shadow_report import build_shadow_report
    data = await build_shadow_report()
    resp = ShadowReportResponse(**data, generated_at=now)
    _cache = (now, resp)
    return resp
