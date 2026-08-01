"""Ambang gate Adaptive Learning Engine — SATU sumber kebenaran.

Masalah yang diselesaikan (audit 1 Agu 2026): angka gate ditulis di EMPAT tempat
terpisah — endpoint SPOT (`signals.py`), endpoint FUTURES, model SPOT (angka
telanjang `60`), dan model FUTURES (`MIN_TRAIN_SAMPLES`). Nilainya kebetulan sama,
tapi tak ada yang menjaganya tetap sama: begitu satu diubah, panel Engine akan
melaporkan "gate lulus" sementara logika promosi sebenarnya menolak — atau
sebaliknya. Persis pola bug yang berulang di repo ini: metrik yang mengklaim
sesuatu berbeda dari kenyataan, dan gagalnya SENYAP.

Mengubah angka di sini mengubah SEKALIGUS syarat promosi model dan tampilan gate,
sehingga keduanya mustahil menyimpang.
"""

from __future__ import annotations

#: Sampel matang minimum sebelum challenger boleh DILATIH.
#: "Matang" = keputusan yang hasil akhirnya sudah diketahui (punya label outcome).
MIN_TRAIN_SAMPLES = 60

#: Baris uji minimum pada holdout sebelum model boleh dianggap layak promosi.
#: Di bawah ini metrik test terlalu berisik untuk dipercaya.
MIN_TEST_SAMPLES = 20

#: Kelengkapan outcome (%) yang dituntut sebelum ledger dianggap sehat.
#: Di bawah ini sebagian keputusan belum berlabel → sampel bias ke yang cepat
#: selesai (menang cepat / rugi cepat), sehingga model belajar dari potongan.
MIN_OUTCOME_COMPLETENESS_PCT = 99.0

#: Outcome minimum sebelum vonis canary boleh difinalisasi.
MIN_CANARY_OBSERVATIONS = 20


def training_gate(mature_samples: int) -> bool:
    return mature_samples >= MIN_TRAIN_SAMPLES


def test_gate(test_n: int) -> bool:
    return test_n >= MIN_TEST_SAMPLES


def completeness_gate(pct: float) -> bool:
    return pct >= MIN_OUTCOME_COMPLETENESS_PCT


# ── Penjelas gate ─────────────────────────────────────────────────────────────
# Panel Engine dulu hanya menampilkan lulus/gagal — pembaca tak bisa tahu SEBERAPA
# JAUH dari lulus, apa yang menghambat, atau kira-kira kapan terpenuhi. Akibatnya
# "model belum promote" terbaca seperti kerusakan, padahal seringkali sekadar
# "kurang N sampel lagi". Fungsi di bawah mengubah boolean jadi diagnosis.

def _pct(cur: float, need: float) -> float:
    return round(min(100.0, cur / need * 100), 1) if need else 100.0


def describe_gates(
    *,
    mature_samples: int,
    test_n: int,
    outcome_completeness_pct: float,
    quality: dict[str, int],
    promotion_eligible: bool,
    champion_exists: bool,
    mature_gain_per_day: float | None = None,
) -> list[dict]:
    """Diagnosis tiap gate: nilai sekarang vs syarat, plus apa artinya.

    `mature_gain_per_day` (opsional) dipakai memperkirakan sisa waktu — hanya
    ditampilkan bila lajunya diketahui, supaya tak mengarang perkiraan.
    """
    bad_quality = {k: v for k, v in (quality or {}).items() if v}
    eta_days = None
    if mature_gain_per_day and mature_gain_per_day > 0 and mature_samples < MIN_TRAIN_SAMPLES:
        eta_days = round((MIN_TRAIN_SAMPLES - mature_samples) / mature_gain_per_day, 1)

    return [
        {
            "key": "training_data",
            "label": "Data latih cukup",
            "passed": training_gate(mature_samples),
            "current": mature_samples,
            "required": MIN_TRAIN_SAMPLES,
            "progress_pct": _pct(mature_samples, MIN_TRAIN_SAMPLES),
            "eta_days": eta_days,
            "blocker": None if training_gate(mature_samples)
                       else f"kurang {MIN_TRAIN_SAMPLES - mature_samples} keputusan matang lagi",
        },
        {
            "key": "test_samples",
            "label": "Sampel uji cukup",
            "passed": test_gate(test_n),
            "current": test_n,
            "required": MIN_TEST_SAMPLES,
            "progress_pct": _pct(test_n, MIN_TEST_SAMPLES),
            "blocker": None if test_gate(test_n)
                       else ("model belum pernah dilatih" if test_n == 0
                             else f"kurang {MIN_TEST_SAMPLES - test_n} baris uji lagi"),
        },
        {
            "key": "outcome_completeness",
            "label": "Hasil sudah terlabel",
            "passed": completeness_gate(outcome_completeness_pct),
            "current": outcome_completeness_pct,
            "required": MIN_OUTCOME_COMPLETENESS_PCT,
            "progress_pct": _pct(outcome_completeness_pct, MIN_OUTCOME_COMPLETENESS_PCT),
            "blocker": None if completeness_gate(outcome_completeness_pct)
                       else (f"{round(100 - outcome_completeness_pct, 1)}% keputusan belum berlabel "
                             "— model akan belajar dari potongan data"),
        },
        {
            "key": "data_quality",
            "label": "Kualitas data bersih",
            "passed": not bad_quality,
            "current": sum(bad_quality.values()),
            "required": 0,
            "progress_pct": 100.0 if not bad_quality else 0.0,
            "blocker": None if not bad_quality
                       else "ada " + ", ".join(f"{k}={v}" for k, v in bad_quality.items()),
        },
        {
            "key": "promotion_eligible",
            "label": "Model layak dipromosikan",
            "passed": bool(promotion_eligible),
            "current": int(bool(promotion_eligible)),
            "required": 1,
            "progress_pct": 100.0 if promotion_eligible else 0.0,
            "blocker": None if promotion_eligible
                       else "model terbaru belum mengalahkan baseline pada data uji",
        },
        {
            "key": "champion_exists",
            "label": "Sudah ada model dipakai",
            "passed": bool(champion_exists),
            "current": int(bool(champion_exists)),
            "required": 1,
            "progress_pct": 100.0 if champion_exists else 0.0,
            "blocker": None if champion_exists
                       else "belum ada model yang lulus sampai tahap dipakai penuh",
        },
    ]
