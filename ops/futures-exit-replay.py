"""Gerbang Fase 4 — putar ulang keputusan keluar historis lewat aturan baru.

Menjawab tiga pertanyaan sebelum satu pun posisi nyata dikelola aturan ini:

  1. Berapa banyak trade yang AKAN menyentuh TP1 di 1,2 ATR? (dulu 4% menyentuh
     TP di 4-8 ATR)
  2. Berapa banyak `sl_plus` impas yang TIDAK LAGI terjadi, karena breakeven
     kini menuntut untung >= 3x biaya? (gerbangnya: harus NOL)
  3. Seberapa jauh harga sempat melewati SL, dan berapa yang akan tertangkap
     lebih awal oleh loop cepat berbasis jarak-ke-SL?

Sumber datanya `exit_events` — puncak gerak favorable (`mfe_atr`) dan adverse
(`mae_atr`) yang BENAR-BENAR terjadi, dinormalkan ATR. Jadi ini bukan simulasi
harga: ia memakai sejauh mana harga sungguh bergerak, lalu bertanya apa yang
akan diputuskan aturan baru pada gerak yang sama.

BATASNYA, dan ini penting: ledger hanya menyimpan puncak, bukan URUTAN. Jadi ia
bisa menjawab "apakah TP1 akan tersentuh" tapi TIDAK "apa yang tersentuh lebih
dulu". Angka di bawah adalah batas atas untuk TP dan batas bawah untuk SL.

Pakai:
    backend/.venv/Scripts/python.exe ops/futures-exit-replay.py
"""

import asyncio
import statistics

from sqlalchemy import text

from agents.futures import exit_config as ecfg
from app.database import AsyncSessionLocal, probe_db, set_db_available


async def main() -> None:
    set_db_available(await probe_db())
    await ecfg.refresh()
    tp1 = ecfg.get("exit_tp1_atr_mult")
    tp2 = ecfg.get("exit_tp2_atr_mult")
    be_cost = ecfg.get("exit_be_arm_cost_mult")
    be_atr = ecfg.get("exit_be_arm_atr")

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT e.close_reason, e.pnl_pct, e.pnl_dollar, e.mfe_atr, e.mae_atr,
                   e.tp_dist_atr, e.held_hours, e.atr_pct, e.lane,
                   t.position_size, (t.signals_json::json->>'cost_floor_pct')::float cost_pct
            FROM exit_events e LEFT JOIN paper_trades t ON t.id = e.trade_id
            WHERE e.market='futures'
        """))).all()

    print(f"parameter: TP1 {tp1}xATR | TP2 {tp2}xATR | breakeven >= {be_cost}x biaya "
          f"DAN >= {be_atr}xATR")
    print(f"keputusan keluar dinilai: {len(rows)}\n")

    ber_mfe = [r for r in rows if r.mfe_atr is not None]
    kena_tp1 = [r for r in ber_mfe if r.mfe_atr >= tp1]
    kena_tp2 = [r for r in ber_mfe if r.mfe_atr >= tp2]
    kena_tp_lama = [r for r in ber_mfe if r.tp_dist_atr and r.mfe_atr >= r.tp_dist_atr]

    print("== 1. APAKAH TP TERCAPAI? ==")
    print(f"punya data MFE            {len(ber_mfe)}")
    print(f"menyentuh TP LAMA         {len(kena_tp_lama):3d}  ({len(kena_tp_lama)/max(len(ber_mfe),1)*100:4.1f}%)"
          f"   (TP dipasang median {statistics.median([r.tp_dist_atr for r in ber_mfe if r.tp_dist_atr]):.1f}xATR)")
    print(f"menyentuh TP1 BARU        {len(kena_tp1):3d}  ({len(kena_tp1)/max(len(ber_mfe),1)*100:4.1f}%)   <- gerbang: >= 30%")
    print(f"menyentuh TP2 BARU        {len(kena_tp2):3d}  ({len(kena_tp2)/max(len(ber_mfe),1)*100:4.1f}%)")

    print("\n== 2. IMPAS SELEVEL FEE - MASIH TERJADI? ==")
    lock = ecfg.get("exit_be_lock_frac")
    sl_plus = [r for r in rows if r.close_reason == "sl_plus"]
    masih, hasil_baru = [], []
    for r in sl_plus:
        biaya = r.cost_pct if r.cost_pct else 0.20
        atrp = r.atr_pct or 0.0
        puncak_pct = (r.mfe_atr or 0.0) * atrp
        if puncak_pct < max(be_cost * biaya, be_atr * atrp):
            continue                       # rem tak menyala; posisi dibiarkan jalan
        masih.append(r)
        # Rem BARU mengunci sebagian puncak (lantai: biaya). Kalau tersentuh,
        # inilah yang dibukukan - bukan nol.
        kunci_pct = max(biaya, puncak_pct * lock)
        notional = r.position_size or 0.0
        hasil_baru.append((kunci_pct - biaya) / 100 * notional)
    tak_lagi = len(sl_plus) - len(masih)
    lama_total = sum(r.pnl_dollar or 0 for r in sl_plus)
    print(f"`sl_plus` historis        {len(sl_plus):3d}  total ${lama_total:+.2f}"
          f"  (rata ${lama_total/max(len(sl_plus),1):+.2f})")
    print(f"  rem TAK menyala         {tak_lagi:3d}  <- dibiarkan jalan, tak ditutup impas")
    print(f"  rem menyala             {len(masih):3d}")
    if hasil_baru:
        impas = sum(1 for r, h in zip(masih, hasil_baru)
                    if h < (r.cost_pct or 0.20) / 100 * (r.position_size or 0))
        m_lama = sum(r.pnl_dollar or 0 for r in masih)
        print(f"    hasil LAMA            ${m_lama:+.2f}  (rata ${m_lama/len(masih):+.2f})")
        print(f"    hasil BARU (kunci {lock:.0%})  ${sum(hasil_baru):+.2f}  "
              f"(rata ${sum(hasil_baru)/len(hasil_baru):+.2f})")
        status = "  LULUS" if impas == 0 else "  GAGAL"
        print(f"    masih impas           {impas:3d}  <- GERBANG: harus 0{status}")
    else:
        print("    masih impas             0  <- GERBANG LULUS")

    print("\n== 3. SL — SEBERAPA JAUH TERTEMBUS ==")
    sl_kena = [r for r in rows if r.close_reason in ("sl_hit", "hist:sl", "fail_fast", "hist:fail_fast")]
    ber_mae = [r for r in sl_kena if r.mae_atr is not None]
    if ber_mae:
        mae = sorted(r.mae_atr for r in ber_mae)
        print(f"gerak adverse (xATR)      median {statistics.median(mae):.2f}  p90 {mae[int(len(mae)*0.9)]:.2f}  maks {mae[-1]:.2f}")
        print(f"  ^ loop cepat baru menjaga posisi begitu jaraknya <= "
              f"{ecfg.get('exit_fast_loop_atr')}xATR dari SL, bukan menunggu leverage >= 10x")
    ff = [r for r in rows if r.close_reason in ("fail_fast", "hist:fail_fast")]
    print(f"\n`fail_fast` historis      {len(ff):3d}  total ${sum(r.pnl_dollar or 0 for r in ff):+.2f}  "
          f"menang {sum(1 for r in ff if (r.pnl_dollar or 0) > 0)}")
    print("  ^ tak ada di aturan baru")

    print("\n== 4. MEKANISME YANG DIHAPUS ==")
    dipakai = {}
    for r in rows:
        dipakai[r.close_reason] = dipakai.get(r.close_reason, 0) + 1
    baru = {"sl_hit", "sl_plus", "tp1_hit", "tp2_hit", "trail_hit", "time_stop",
            "liq_guard", "emergency_close"}
    for reason, n in sorted(dipakai.items(), key=lambda x: -x[1]):
        pokok = reason.replace("hist:", "")
        tanda = "tetap" if pokok in baru or f"{pokok}_hit" in baru else "DIHAPUS"
        print(f"  {reason:24s} {n:4d}  {tanda}")

    print("\nCATATAN: ledger menyimpan PUNCAK gerak, bukan urutannya. Jadi angka TP")
    print("di atas adalah batas ATAS (belum tentu TP tersentuh sebelum SL), dan")
    print("angka SL batas BAWAH. Yang layak disimpulkan: arah dan besaran, bukan")
    print("jumlah pastinya.")


if __name__ == "__main__":
    asyncio.run(main())
