/**
 * Registry agen — SATU sumber kebenaran untuk nama & pengelompokan agen di UI.
 *
 * Masalah yang diselesaikan (audit 30 Jul 2026): pemetaan nama agen ditulis ulang
 * di banyak komponen memakai rantai ternary. Saat lane `futures_agent_bigmover`
 * lahir, komponen-komponen itu tak ikut diperbarui sehingga posisi BigMover
 * DILABELI "Accum" — bukan sekadar hilang, tapi SALAH NAMA, dan tak ada error
 * yang muncul. Contoh pola lama yang berbahaya:
 *
 *     agent === "futures_agent1" ? "Pre" : agent === "futures_agent3" ? "Momo" : "Accum"
 *                                                                       ^ semua lane
 *                                                                         lain jatuh
 *                                                                         ke sini
 *
 * Padanan backend: `backend/app/services/agent_registry.py` (sumbernya
 * `agents.futures.weight_updater.FUTURES_AGENTS`).
 */

export const SPOT_AGENT = "opportunity_spot";
export const CROSS_AGENT = "cross_agent";

/** Berbasis prefix supaya lane baru ikut terhitung walau belum diberi label. */
export const isFuturesAgent = (agent: string): boolean => agent.startsWith("futures_");

const LABELS: Record<string, string> = {
  [SPOT_AGENT]:             "SPOT",
  futures_agent1:           "Pre-Gainer",
  futures_agent2:           "Accumulation",
  futures_agent3:           "Momentum",
  futures_agent_bigmover:   "BigMover",
  [CROSS_AGENT]:            "Cross-Agent",
};

const SHORT: Record<string, string> = {
  [SPOT_AGENT]:             "SPOT",
  futures_agent1:           "Pre",
  futures_agent2:           "Accum",
  futures_agent3:           "Momo",
  futures_agent_bigmover:   "BigMover",
  [CROSS_AGENT]:            "Cross",
};

/** Warna per lane; lane tak dikenal memakai netral (bukan warna lane lain). */
const COLORS: Record<string, string> = {
  [SPOT_AGENT]:             "text-teal-700",
  futures_agent1:           "text-blue-700",
  futures_agent2:           "text-purple-700",
  futures_agent3:           "text-orange-700",
  futures_agent_bigmover:   "text-amber-700",
  [CROSS_AGENT]:            "text-neutral-700",
};

/**
 * Nama panjang. Lane yang belum dikatalogkan mengembalikan kunci mentahnya —
 * SENGAJA: lebih baik terlihat "futures_agent_scalper" daripada salah dinamai
 * lane lain seperti bug BigMover→"Accum".
 */
export const agentLabel = (agent: string): string => LABELS[agent] ?? agent;

/** Nama pendek untuk tabel/badge sempit, dengan fallback yang tetap terbaca. */
export const agentShort = (agent: string): string =>
  SHORT[agent] ?? (agent.replace("futures_agent_", "").replace("futures_agent", "A") || agent);

export const agentColor = (agent: string): string => COLORS[agent] ?? "text-neutral-700";

/**
 * Lane futures → agen pemiliknya. Cermin `AGENT_LANE` di
 * `backend/app/services/agent_registry.py` (arah terbalik).
 *
 * Dipakai supaya label lane tidak ditulis ulang: nama tetap datang dari `LABELS`
 * di atas, jadi mengganti nama sebuah lane cukup di satu tempat.
 */
const LANE_AGENT: Record<string, string> = {
  pre_gainer:   "futures_agent1",
  accumulation: "futures_agent2",
  momentum:     "futures_agent3",
  bigmover:     "futures_agent_bigmover",
  pre_move:     "futures_agent1",   // alias lama
};

/**
 * Nama ramah untuk sebuah lane futures. Lane yang belum dikatalogkan
 * mengembalikan kunci mentahnya — sengaja, karena salah nama lebih berbahaya
 * daripada nama teknis (pelajaran BigMover→"Accum").
 */
export const futuresLaneLabel = (lane: string): string => {
  const agent = LANE_AGENT[lane];
  return agent ? agentLabel(agent) : lane;
};

export const futuresLaneColor = (lane: string): string =>
  agentColor(LANE_AGENT[lane] ?? "");
