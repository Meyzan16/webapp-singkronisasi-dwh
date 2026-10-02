# Gerbang Fase 7 — 2026-10-02

Dihasilkan `ops/futures-gate.py` pada 2026-10-02 23:12.
**Jangan diedit tangan** — jalankan ulang skripnya.

## Putusan: BELUM LULUS — ukuran TETAP

| gerbang | sekarang | syarat | lulus |
|---|---|---|---|
| sampel cukup | 126 | >= 40 | ✅ |
| ekspektasi bersih/trade | -0.5 | > $0 | ❌ |
| TP1/TP2 tersentuh | 27.8% | >= 30% | ❌ |
| trade impas | 34.1% | <= 10% | ❌ |
| win rate bermakna | 38.6% | >= 35% | ✅ |
| untung:biaya pemenang | 20.3x | >= 5x | ✅ |
| kerugian terkendali | breach maks 6.69%, 0 rugi > 1,3x risk | breach <= 0,5% & 0 kejadian | ❌ |
| drawdown puncak | 11.3% | <= 15% | ✅ |

## Kenapa tiap gerbang ada

- **sampel cukup** — Di bawah ini, apa pun yang terlihat masih derau.
- **ekspektasi bersih/trade** — Memperbesar ukuran sistem berekspektasi negatif hanya mempercepat rugi.
- **TP1/TP2 tersentuh** — Sistem lama: 4%. TP yang tak pernah tercapai bukan TP.
- **trade impas** — Sistem lama: 75%. Inilah 'ditutup 0% kemakan fee'.
- **win rate bermakna** — Dihitung atas trade TEGAS saja — impas bukan menang, bukan kalah.
- **untung:biaya pemenang** — Menang yang cuma menutup fee bukan kemenangan.
- **kerugian terkendali** — Sistem lama: BLUAI rugi 2,16x risiko yang direncanakan.
- **drawdown puncak** — Batas yang sama dipakai circuit breaker.

## Yang menghalangi

Gerbang berikut belum lulus, jadi `size_risk_base_pct` TETAP:

- ekspektasi bersih/trade
- TP1/TP2 tersentuh
- trade impas
- kerugian terkendali

Menaikkan ukuran sekarang berarti memperbesar sistem yang
belum terbukti — persis yang dihindari prinsip P1 di plan.
