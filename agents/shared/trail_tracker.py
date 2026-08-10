"""Pelacak gerak harga SESUDAH TP1 — bahan belajar untuk dua parameter trailing.

Kenapa modul terpisah, dan kenapa satuannya bukan persen atau ATR:

`TRAIL_LOCK_AFTER_TP1_FRAC` dan `TRAIL_ADVANCE_TP1_TP2_FRAC` dua-duanya
dinyatakan sebagai PECAHAN dari jarak (TP1−entry) dan (TP2−TP1). Kalau bukti
yang dikumpulkan berupa persen harga atau kelipatan ATR, mengubahnya jadi usulan
angka parameter butuh konversi yang bergantung pada TP1/TP2 tiap trade — dan
TP1/TP2 tidak disimpan di ledger. Jadi bukti dikumpulkan langsung dalam SATUAN
PARAMETERNYA SENDIRI:

    fav = kemajuan harga dalam satuan TP1
          0.0 = di entry, 1.0 = tepat di TP1, 2.0 = sejauh dua kali TP1

Dengan itu `retrace_after_tp1_frac` bisa dibandingkan APEL-KE-APEL dengan
`TRAIL_LOCK_AFTER_TP1_FRAC` (dua-duanya pecahan TP1), dan `ext_after_tp1_frac`
dengan `TRAIL_ADVANCE_TP1_TP2_FRAC` (dua-duanya pecahan TP1→TP2).

Acuan TP1/TP2 DIBEKUKAN saat TP1 tersentuh, karena monitor memutasi
`trade.take_profit` setelah TP1 (naik ke TP2 lalu TP3). Membaca acuan saat
penutupan akan mengukur terhadap target yang sudah berpindah — pecahannya jadi
tidak berarti.

MAE global (`mae_atr`) TIDAK bisa menggantikan ini: ia mencakup periode SEBELUM
TP1, jadi titik terdalamnya biasanya terjadi saat posisi baru dibuka — sama
sekali bukan pertanyaan yang ditanyakan trailing.
"""

from __future__ import annotations


def arm_tp1(meta: dict, *, entry: float, tp1: float, tp2: float | None,
            direction: str = "LONG") -> None:
    """Bekukan acuan TP1/TP2 pada saat TP1 tersentuh. Idempoten."""
    if meta.get("tp1_ref_armed"):
        return
    span = (tp1 - entry) if direction == "LONG" else (entry - tp1)
    if not entry or span <= 0:
        return  # TP1 tak masuk akal — jangan cemari ledger dengan pecahan karangan
    meta["tp1_ref_armed"] = True
    meta["tp1_ref_entry"] = float(entry)
    meta["tp1_ref_span"]  = float(span)
    meta["tp1_ref_dir"]   = "LONG" if direction == "LONG" else "SHORT"
    # Besar keuntungan di TP1 (harga%). Tanpa ini pertanyaan "berapa hasilnya
    # ANDAI berhenti di level 0,9×TP1" tak bisa dihitung — dan rekomendasi
    # terpaksa jadi heuristik alih-alih perbandingan hasil.
    meta["tp1_gain_pct"] = round(span / entry * 100, 4)
    if tp2:
        tp2_fav = ((tp2 - entry) / span if direction == "LONG"
                   else (entry - tp2) / span)
        # TP2 harus BENAR-BENAR di luar TP1, kalau tidak penyebutnya nol/negatif.
        if tp2_fav > 1.0:
            meta["tp2_fav"] = round(tp2_fav, 4)
    # Titik awal = tepat di TP1 (fav 1.0), bukan 0 — biar trade yang langsung
    # lanjut naik tak tercatat seolah pernah balik ke entry.
    meta["fav_min_after_tp1"] = 1.0
    meta["fav_max_after_tp1"] = 1.0


def track(meta: dict, price: float) -> bool:
    """Perbarui titik terjauh dua arah sesudah TP1. True bila ada perubahan."""
    if not meta.get("tp1_ref_armed") or not price:
        return False
    entry = float(meta.get("tp1_ref_entry") or 0.0)
    span  = float(meta.get("tp1_ref_span") or 0.0)
    if span <= 0:
        return False
    fav = ((price - entry) / span if meta.get("tp1_ref_dir") == "LONG"
           else (entry - price) / span)
    changed = False
    if fav < float(meta.get("fav_min_after_tp1", 1.0)):
        meta["fav_min_after_tp1"] = round(fav, 4)
        changed = True
    if fav > float(meta.get("fav_max_after_tp1", 1.0)):
        meta["fav_max_after_tp1"] = round(fav, 4)
        changed = True
    return changed


def fractions(meta: dict) -> tuple[float | None, float | None]:
    """`(retrace_after_tp1_frac, ext_after_tp1_frac)` untuk ledger.

    - retrace: titik TERENDAH sesudah TP1, dalam satuan TP1. 1.0 = tak pernah
      balik sedikit pun; 0.75 = pernah turun tepat ke level kunci saat ini;
      di bawah 0 = sempat merugi.
    - ext: kemajuan TERJAUH ke arah TP2, 0 = tak pernah lewat TP1, 1.0 = sampai
      TP2. `None` bila TP2 tak diketahui — lebih baik kosong daripada dikarang.
    """
    if not meta.get("tp1_ref_armed"):
        return None, None
    retrace = meta.get("fav_min_after_tp1")
    ext = None
    tp2_fav = meta.get("tp2_fav")
    fav_max = meta.get("fav_max_after_tp1")
    if tp2_fav and fav_max is not None and float(tp2_fav) > 1.0:
        ext = round((float(fav_max) - 1.0) / (float(tp2_fav) - 1.0), 4)
    return (round(float(retrace), 4) if retrace is not None else None), ext
