# Garis dasar FUTURES — 2026-09-05

Dihasilkan otomatis oleh `ops/futures-baseline.py` pada
2026-09-05T20:17:51.
**Jangan diedit tangan** — jalankan ulang skripnya untuk memperbarui.

Ini keadaan SEBELUM rewrite agentic (PLAN-FUTURES-AGENTIC.md). Fase 7 menjalankan
skrip yang sama untuk membandingkan apel dengan apel.

## Wallet
| balance | awal | realized |
|---|---|---|
| 854.39 | 1000.00 | -145.61 |

## Ukuran posisi
| risk_p50 | notional_p50 | margin_p50 | lev_avg | sl_p25 | sl_p50 | sl_p75 | tp_p50 | n |
|---|---|---|---|---|---|---|---|---|
| 4.98 | 95.8 | 32.3 | 2.77 | 4.52 | 5.28 | 7.99 | 18.41 | 112 |

## Win rate: resmi vs bermakna
| n | wr_resmi | wr_ge1 | wr_ge3 | scratch_lt050 | total_usd |
|---|---|---|---|---|---|
| 110 | 50.0 | 10.9 | 6.4 | 43 | -145.47 |

`wr_resmi` memakai definisi `pnl_pct > 0` (bug B1 — scratch selevel fee ikut terhitung menang).
`wr_ge1` / `wr_ge3` = kemenangan yang benar-benar membukukan ≥ $1 / ≥ $3.

## Per lane
| style | n | tp | sl | usd | lev |
|---|---|---|---|---|---|
| futures_agent_bigmover | 91 | 5 | 86 | -87.26 | 2.6 |
| futures_agent3 | 15 | 0 | 15 | -54.99 | 3.8 |
| futures_agent1 | 3 | 0 | 2 | -13.15 | 2.7 |
| futures_agent2 | 3 | 0 | 2 | 9.79 | 3.0 |

## Alasan keluar (exit_events)
| close_reason | n | avg_pct | usd | hold_h | mfe_atr | tp_atr |
|---|---|---|---|---|---|---|
| hist:sl | 35 | -0.51 | -36.51 | 6.1 | 0.92 | 6.46 |
| sl_plus | 31 | 0.25 | 9.41 | 0.7 | 0.67 | 4.19 |
| sl_hit | 25 | -3.16 | -58.48 | 1.5 | 0.14 | 4.00 |
| hist:fail_fast | 8 | -3.60 | -43.70 | 0.5 | 0.38 | 8.50 |
| tp2_hit | 4 | 2.75 | 11.70 | 0.6 | 0.60 | 4.00 |
| fail_fast | 3 | -9.02 | -35.39 | 0.4 | 0.15 | 4.00 |
| hist:tp | 1 | 13.04 | 14.29 | 7.8 | 3.56 | 4.02 |

## Kerugian melebihi rencana (bug B2)
| n_rugi_lebih_dari_risk | rasio_maks | rugi_rata | risk_rata |
|---|---|---|---|
| 19 | 2.16 | 6.46 | 5.33 |

## Kelengkapan ledger (bug B3)
| trade_tanpa_exit_event |
|---|
| 5 |

## Ledger keputusan
| total | berlabel | agen |
|---|---|---|
| 7418 | 7373 | 4 |

## Gerbang Fase 7 (harus dilampaui sebelum ukuran naik penuh)

| gerbang | garis dasar hari ini | target |
|---|---|---|
| ekspektasi bersih / trade | negatif | > 0 |
| `tp1_hit` | 4 % | ≥ 30 % |
| scratch (\|pnl\| < 2× biaya) | ~35 % | ≤ 10 % |
| WR bermakna (≥ $3) | 6.4 % | ≥ 35 % |
| rugi > 1,3× risk | 19 kejadian | 0 |
| trade tanpa exit_event | 5 | 0 |
