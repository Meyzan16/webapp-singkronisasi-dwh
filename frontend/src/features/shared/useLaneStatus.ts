"use client";
import { apiFetch } from "@/lib/api";
import { useEffect, useState } from "react";

/**
 * Status pakai tiap lane futures — dibaca dari keadaan, bukan daftar hardcode.
 *
 * Dipakai untuk MENYEMBUNYIKAN lane yang tidak dipakai dari tampilan yang melihat
 * ke depan (posisi terbuka, tab scanner, ringkasan margin). Lane yang quota-nya 0
 * tak akan pernah membuka posisi, dan panel permanen kosong terbaca seolah lane itu
 * sedang menunggu sinyal.
 *
 * Dua hal yang sengaja TIDAK dilakukan di sini:
 *
 * 1. **`bigmover` tak pernah disembunyikan.** Ia tidak ada di `lane_quotas` sama
 *    sekali — batasnya `MAX_BIGMOVER_POSITIONS`, jalur yang lain. Aturan
 *    "quota 0 → sembunyikan" yang ditulis naif akan melenyapkan lane paling aktif.
 *    Karena itu yang dipakai `quota === 0`, bukan `!quota`.
 *
 * 2. **Riwayat tak disembunyikan.** Lane mati boleh hilang dari tampilan ke-depan,
 *    tapi trade dan exit-nya sudah terjadi: `momentum` meninggalkan 14 trade tertutup
 *    dan kerugian −54,99 yang justru menjadi dasar keputusan mematikannya. Hook ini
 *    hanya untuk sisi ke-depan.
 *
 * Saat quota dikembalikan (mis. momentum → 2), panelnya muncul sendiri tanpa
 * sentuhan kode.
 */
export interface LaneStatus {
  /** {lane: quota} dari /agent/config. `null` selagi dimuat / bila gagal. */
  quotas: Record<string, number> | null;
  /** True hanya bila lane TERDAFTAR di quota DAN nilainya 0. */
  isDisabled: (lane: string) => boolean;
  loading: boolean;
}

/** Nama lane pada `lane_quotas` untuk sebuah style agen. */
export function laneOfAgent(agent: string): string {
  return agent.replace(/^futures_agent_?/, "") || agent;
}

export function useLaneStatus(): LaneStatus {
  const [quotas, setQuotas] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let batal = false;
    apiFetch("/api/v1/agent/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (batal) return;
        const q = d?.futures?.auto_trader?.lane_quotas;
        setQuotas(q && typeof q === "object" ? (q as Record<string, number>) : null);
      })
      .catch(() => { if (!batal) setQuotas(null); })
      .finally(() => { if (!batal) setLoading(false); });
    return () => { batal = true; };
  }, []);

  return {
    quotas,
    loading,
    // Selagi quota belum termuat, TIDAK ada yang disembunyikan. Menyembunyikan
    // lane karena permintaan gagal akan membuat lane hidup ikut lenyap.
    isDisabled: (lane: string) => quotas?.[lane] === 0,
  };
}
