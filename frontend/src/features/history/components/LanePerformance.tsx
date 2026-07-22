"use client";
import { LANES } from "@/lib/lanes";
import type { LaneFunnel, ScanMeta } from "./OppSpotTypes";

// PLAN_v9 G1a — performa per LANE, dinamis dari data aktual (bukan 3-tipe hardcode).
// Ini memperbaiki bug lama di mana trade BigMover & Early Radar tak pernah muncul.
export interface LaneStat {
  key:     string;
  label:   string;
  emoji:   string;
  total:   number;   // trade selesai (tp/sl) di lane ini
  wins:    number;
  winRate: number;
  avgPnl:  number;
  pnl$:    number;
  open:    number;   // posisi yang masih terbuka di lane ini
}

interface LanePerformanceProps {
  laneStats:  LaneStat[];
  windowDays: number;
  scanMeta?:  ScanMeta | null;
}

/**
 * S2 — ringkasan corong satu lane dari scan terakhir, sebagai kalimat.
 * Menjawab "kenapa lane ini kosong" dengan angka, bukan tebakan.
 */
function funnelSummary(f?: LaneFunnel): string | null {
  if (!f || f.pool === 0) return null;
  if (f.found > 0) {
    return `Scan terakhir: ${f.pool} kandidat → ${f.found} lolos, ${f.auto_eligible} layak auto-open`;
  }
  const gugur = [
    f.rejected_score    ? `${f.rejected_score} gugur skor`       : null,
    f.rejected_levels   ? `${f.rejected_levels} gugur level/R:R` : null,
    f.rejected_net_ev   ? `${f.rejected_net_ev} gugur net-EV`    : null,
    f.rejected_learning ? `${f.rejected_learning} diveto learning` : null,
    f.no_data           ? `${f.no_data} data kurang`             : null,
  ].filter(Boolean).join(" · ");
  return `Scan terakhir: ${f.pool} kandidat${gugur ? ` → ${gugur}` : ""} → 0 lolos`;
}

export function LanePerformance({ laneStats, windowDays, scanMeta }: LanePerformanceProps) {
  const funnels = scanMeta?.lane_funnel ?? {};
  const regime  = scanMeta?.regime_status;
  const breadth = scanMeta?.alt_breadth_pct;

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-1">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">
          🛣 Win Rate per Lane
        </p>
        <a href="/signals" className="text-[10px] font-semibold text-teal-600 hover:underline">
          Analisa sinyal individual → /signals
        </a>
      </div>
      <p className="text-[10px] text-neutral-400 mb-2">
        Semua {laneStats.length} lane SPOT yang di-scan agent · trade selesai (TP/SL) {windowDays} hari terakhir.
        Lane tanpa angka bukan hilang — memang belum menghasilkan trade.
      </p>

      {/* S2 — status gerbang pasar: kenapa auto-open mungkin sedang ditahan */}
      {regime && (
        <div className={`mb-3 text-[10px] rounded-lg px-2.5 py-1.5 border ${
          regime === "CLOSED"  ? "bg-red-50 border-red-200 text-red-700"
          : regime === "REDUCED" ? "bg-amber-50 border-amber-200 text-amber-700"
          : "bg-neutral-50 border-neutral-200 text-neutral-500"
        }`}>
          <strong>Gerbang pasar: {regime}</strong>
          {scanMeta?.btc_regime ? ` · ${scanMeta.btc_regime}` : ""}
          {breadth != null ? ` · breadth alt ${breadth.toFixed(0)}% hijau` : ""}
          {regime === "REDUCED" && " — kuota auto-open dipotong jadi 1 per cycle"}
          {regime === "CLOSED"  && " — auto-open dihentikan sementara"}
        </div>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {laneStats.map(l => {
          const badge = LANES[l.key]?.badge ?? "bg-neutral-100 text-neutral-600";
          // Ambang HIDUP dari scan; konstanta frontend hanya cadangan saat scan
          // belum termuat. Tanpa ini kartu menampilkan angka basi begitu threshold
          // diubah lewat agent_config (mis. BigMover 65 → 71 di B-Fix 1).
          const auto  = scanMeta?.lane_thresholds?.[l.key]?.auto ?? LANES[l.key]?.autoScore;
          const idle  = l.total === 0;
          return (
            <div
              key={l.key}
              className={`rounded-xl p-3 border ${idle ? "border-dashed border-neutral-200 bg-white" : "border-neutral-200 bg-neutral-50"}`}
            >
              <div className="flex items-center gap-1.5 mb-1">
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${badge} ${idle ? "opacity-60" : ""}`}>
                  {l.emoji} {l.label}
                </span>
              </div>
              {idle ? (
                <>
                  <p className="text-xl font-black text-neutral-300">—</p>
                  <p className="text-[10px] text-neutral-400">
                    0 trade selesai{auto != null ? ` · auto ≥${auto}` : ""}
                  </p>
                  <p className="text-[10px] text-neutral-400">
                    {l.open > 0
                      ? `${l.open} posisi masih terbuka`
                      : (funnelSummary(funnels[l.key]) ?? "belum ada kandidat di universe lane ini")}
                  </p>
                </>
              ) : (
                <>
                  <p className={`text-xl font-black ${l.winRate >= 50 ? "text-green-600" : "text-red-500"}`}>
                    {l.winRate.toFixed(0)}%
                  </p>
                  <p className="text-[10px] text-neutral-400">
                    {l.wins}/{l.total} trades{auto != null ? ` · auto ≥${auto}` : ""}
                    {l.open > 0 ? ` · ${l.open} terbuka` : ""}
                  </p>
                  <p className={`text-[10px] font-semibold ${l.avgPnl >= 0 ? "text-green-500" : "text-red-400"}`}>
                    avg {l.avgPnl >= 0 ? "+" : ""}{l.avgPnl.toFixed(1)}%
                  </p>
                  <p className={`text-[10px] font-bold ${l.pnl$ >= 0 ? "text-green-600" : "text-red-500"}`}>
                    {l.pnl$ >= 0 ? "+" : ""}${l.pnl$.toFixed(2)}
                  </p>
                </>
              )}
              {(() => {
                const s = funnelSummary(funnels[l.key]);
                return s && !idle
                  ? <p className="text-[9px] text-neutral-400 mt-1 leading-snug border-t border-neutral-200/70 pt-1">{s}</p>
                  : null;
              })()}
            </div>
          );
        })}
      </div>
    </div>
  );
}
