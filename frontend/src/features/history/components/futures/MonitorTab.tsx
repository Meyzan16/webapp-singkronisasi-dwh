"use client";
import { EmptyState } from "@/components/ui/feedback";
import { useLaneStatus } from "@/features/shared/useLaneStatus";
import { GateBanner } from "./GateBanner";
import { OpenPosCard } from "./OpenPosCard";
import type { FuturesPosition, RiskDashboard, LearningStats, RiskPosition } from "./types";
import { calcNotional, calcMargin, tradePnlDollar } from "./types";

/** Satu sumber daftar lane — dulu diulang di tiga tempat (breakdown, chip, kolom),
 *  sehingga lane baru gampang tertinggal di salah satunya tanpa error apa pun. */
const LANES = [
  // Agen tunggal paling depan — satu-satunya yang membuka posisi sekarang.
  // Tanpa baris ini posisinya terhitung di TOTAL margin/notional tapi tak
  // muncul di satu pun kolom lane, dan chip filternya pun tak ada.
  { key: "agentic",        lane: "agentic",      label: "🧠 Agentic",
    chip: "bg-teal-100 text-teal-700 border-teal-200",       dark: "text-teal-300"   },
] as const;

interface Props {
  positions:    FuturesPosition[];
  riskDash:     RiskDashboard | null;
  learning:     LearningStats | null;
  startingBalance: number;
  riskDollar:   number;
  countdown:    number;
  onRefresh:    () => void;
}

export function MonitorTab({ positions, riskDash, learning, startingBalance, riskDollar, countdown, onRefresh }: Props) {
  const { isDisabled } = useLaneStatus();

  // U1: lane yang tak dipakai (quota 0) HILANG dari tampilan ke-depan. Panel yang
  // permanen kosong terbaca seolah lane sedang menunggu sinyal, padahal ia tak akan
  // pernah membuka posisi. Riwayatnya tetap utuh di tab lain — trade yang sudah
  // terjadi tak ikut disembunyikan.
  const lanesAktif = LANES.filter(l => !isDisabled(l.lane));
  const lanePauses = riskDash?.gate?.lane_pauses ?? {};

  const pd = riskDash?.portfolio;
  const ab = riskDash?.agent_breakdown;

  const riskMap: Record<number, RiskPosition> = {};
  (riskDash?.positions ?? []).forEach(rp => { riskMap[rp.id] = rp; });

  const openPos = positions.filter(p => p.status === "open");
  const hasOpen = openPos.length > 0;

  // Compute financial summary from positions (same logic as OpenPosCard)
  const getMargin = (p: FuturesPosition) => {
    const notional = p.position_size ?? calcNotional(p.risk_pct, riskDollar);
    return riskMap[p.id]?.margin ?? calcMargin(notional, p.leverage);
  };
  const totalUnrealized = openPos.reduce((s, p) => s + (tradePnlDollar(p, riskDollar) ?? 0), 0);
  const totalMargin     = openPos.reduce((s, p) => s + getMargin(p), 0);

  return (
    <div className="space-y-5">
      <GateBanner gate={riskDash?.gate} />

      {/* Portfolio summary — full data from riskDash, fallback from positions when API unavailable */}
      {pd ? (
        <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
            <div>
              <p className="text-xs text-neutral-400 uppercase tracking-wider font-semibold mb-1">🔍 Portfolio Risk Dashboard</p>
              {(() => {
                const equity = pd.current_balance + pd.total_unrealized;
                const equityDelta = equity - startingBalance;
                return (
                  <>
                    <div className="flex items-baseline gap-3">
                      <span className={`text-4xl font-black ${equity >= startingBalance ? "text-green-400" : "text-red-400"}`}>
                        ${equity.toFixed(2)}
                      </span>
                      <span className={`text-sm font-bold ${equityDelta >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {equityDelta >= 0 ? "+" : ""}${equityDelta.toFixed(2)}
                      </span>
                    </div>
                    <p className="text-xs text-neutral-500 mt-1">
                      Realized ${pd.current_balance.toFixed(2)} · Unrealized {pd.total_unrealized >= 0 ? "+" : ""}${pd.total_unrealized.toFixed(2)}
                      {" · "}Sharpe ≈ {pd.risk_adjusted_return != null ? pd.risk_adjusted_return.toFixed(2) : "—"}
                    </p>
                  </>
                );
              })()}
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                { val: pd.open_count,       cls: "text-blue-400",                                                     label: "Open"   },
                { val: pd.at_risk_count,    cls: pd.at_risk_count > 0 ? "text-red-400" : "text-green-400",            label: "At Risk"},
                { val: `${pd.max_drawdown_pct.toFixed(1)}%`, cls: "text-orange-400",                                  label: "Max DD" },
              ].map(x => (
                <div key={x.label} className="bg-white/5 rounded-xl px-3 py-2">
                  <p className={`text-2xl font-black ${x.cls}`}>{x.val}</p>
                  <p className="text-[9px] text-neutral-400">{x.label}</p>
                </div>
              ))}
            </div>
          </div>

          {ab && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {lanesAktif
                .map(l => ({ ...l, data: (ab as Record<string, { open: number; margin: number; at_risk?: number } | undefined>)[l.key] }))
                .filter(a => a.data).map(a => (
                <div key={a.key} className={`bg-white/5 rounded-xl p-3 border ${(a.data!.at_risk ?? 0) > 0 ? "border-red-700/40" : "border-white/5"}`}>
                  <p className={`text-[10px] font-bold mb-2 ${a.dark}`}>
                    {a.label}
                    {lanePauses[a.lane]?.paused ? <span className="ml-1 text-yellow-400" title="dijeda">⏸</span> : null}
                  </p>
                  <div className="flex flex-col gap-1 text-xs">
                    <span className="text-neutral-400">Open: <strong className="text-white">{a.data!.open}</strong></span>
                    <span className="text-neutral-400">Margin: <strong className="text-yellow-300">${a.data!.margin.toFixed(0)}</strong></span>
                    {(a.data!.at_risk ?? 0) > 0 && <span className="text-red-400 font-bold">⚠️ {a.data!.at_risk} at risk</span>}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="mt-3 flex gap-4 text-xs flex-wrap items-center">
            <span className="text-neutral-400">Total Margin: <strong className="text-yellow-300">${pd.total_margin.toFixed(0)}</strong></span>
            <span className="text-neutral-400">Notional: <strong className="text-neutral-200">${pd.total_notional.toFixed(0)}</strong></span>
            <span className="text-neutral-400">Unrealized: <strong className={pd.total_unrealized >= 0 ? "text-green-400" : "text-red-400"}>
              {pd.total_unrealized >= 0 ? "+" : ""}${pd.total_unrealized.toFixed(2)}
            </strong></span>
            {/* G7: margin ratio warning */}
            {pd.margin_ratio != null && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                pd.margin_ratio > 80
                  ? "bg-red-900/40 text-red-300 border-red-700/60"
                  : pd.margin_ratio > 60
                  ? "bg-yellow-900/40 text-yellow-300 border-yellow-700/60"
                  : "bg-white/5 text-neutral-400 border-white/10"
              }`}>
                {pd.margin_ratio > 80 ? "⚠️ " : pd.margin_ratio > 60 ? "⚡ " : ""}
                Margin Ratio {pd.margin_ratio.toFixed(1)}%
              </span>
            )}
            {/* PLAN_v2 P2.3 — aggregate ROI on margin */}
            {pd.aggregate_roi_pct != null && pd.open_count > 0 && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                pd.aggregate_roi_pct < -50
                  ? "bg-red-900/40 text-red-300 border-red-700/60"
                  : pd.aggregate_roi_pct < 0
                  ? "bg-yellow-900/40 text-yellow-300 border-yellow-700/60"
                  : "bg-green-900/40 text-green-300 border-green-700/60"
              }`}>
                Aggregate ROI {pd.aggregate_roi_pct >= 0 ? "+" : ""}{pd.aggregate_roi_pct.toFixed(1)}%
              </span>
            )}
          </div>
          {/* PLAN_v2 P2.3 — Worst ROI Open */}
          {pd.worst_roi && pd.worst_roi.roi_pct < 0 && (
            <div className="mt-3 rounded-xl bg-red-900/30 border border-red-700/40 px-3 py-2 text-xs">
              <span className="text-neutral-400 mr-2">Worst ROI Open:</span>
              <span className="font-bold text-red-300">{pd.worst_roi.symbol.replace("USDT", "")}</span>
              <span className="text-neutral-500 ml-1">({pd.worst_roi.setup_type ?? pd.worst_roi.agent.replace("futures_", "")})</span>
              <span className={`ml-2 font-bold ${pd.worst_roi.roi_pct < -100 ? "text-red-400 animate-pulse" : "text-red-300"}`}>
                {pd.worst_roi.roi_pct >= 0 ? "+" : ""}{pd.worst_roi.roi_pct.toFixed(1)}%
                {pd.worst_roi.roi_pct < -100 && " ⚠"}
              </span>
              <span className="text-neutral-500 ml-2">
                ${pd.worst_roi.upnl_dollar.toFixed(2)} on ${pd.worst_roi.margin.toFixed(0)} margin · {pd.worst_roi.leverage}x
              </span>
            </div>
          )}
        </div>
      ) : hasOpen ? (
        // MN1: fallback banner computed from positions when riskDash API unavailable
        <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white p-5">
          <p className="text-xs text-neutral-400 uppercase tracking-wider font-semibold mb-3">🔍 Portfolio Risk Dashboard <span className="text-neutral-600 normal-case">(estimasi lokal)</span></p>
          <div className="flex items-baseline gap-3 mb-3">
            <span className={`text-4xl font-black ${totalUnrealized >= 0 ? "text-green-400" : "text-red-400"}`}>
              {totalUnrealized >= 0 ? "+" : ""}${totalUnrealized.toFixed(2)}
            </span>
            <span className="text-sm text-neutral-400">unrealized P&L</span>
          </div>
          <div className="flex gap-4 text-xs flex-wrap">
            <span className="text-neutral-400">Open: <strong className="text-blue-400">{openPos.length}</strong></span>
            <span className="text-neutral-400">Total Margin: <strong className="text-yellow-300">${totalMargin.toFixed(0)}</strong></span>
          </div>
        </div>
      ) : null}

      {/* Posisi terbuka — satu grid kartu, bukan satu kolom per lane.
          Susunan lama memberi SATU KOLOM untuk tiap lane, jadi setelah Fase 8
          menyisakan satu agen, kolomnya melebar penuh ke seluruh layar dan tiap
          posisi terbaca seperti panel raksasa. Sekarang kartunya mengalir
          bersebelahan: 2 di tablet, 3 di layar lebar. */}
      {hasOpen ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 items-start">
          {openPos.map(p => (
            <OpenPosCard key={p.id} p={p} risk={riskMap[p.id]} riskDollar={riskDollar} />
          ))}
        </div>
      ) : (
        <EmptyState icon="📭" title="Tidak ada posisi terbuka saat ini" />
      )}

      {/* Monitor stats */}
      <div className="bg-white border border-neutral-200 rounded-2xl p-4">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📊 Ringkasan Posisi</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
          {/* Unrealized P&L — always computed from positions */}
          <div className={`rounded-xl p-3 ${hasOpen ? (totalUnrealized >= 0 ? "bg-green-50 border border-green-100" : "bg-red-50 border border-red-100") : "bg-neutral-50"}`}>
            <p className={`text-xl font-black tabular-nums ${
              !hasOpen ? "text-neutral-400" : totalUnrealized >= 0 ? "text-green-600" : "text-red-600"
            }`}>
              {hasOpen ? `${totalUnrealized >= 0 ? "+" : ""}$${totalUnrealized.toFixed(2)}` : "—"}
            </p>
            <p className="text-[10px] text-neutral-600 font-semibold mt-1">Unrealized P&L</p>
            <p className="text-[9px] text-neutral-400">{openPos.length} posisi open</p>
          </div>

          {/* Total Margin */}
          <div className={`rounded-xl p-3 ${hasOpen ? "bg-yellow-50 border border-yellow-100" : "bg-neutral-50"}`}>
            <p className={`text-xl font-black tabular-nums ${hasOpen ? "text-yellow-600" : "text-neutral-400"}`}>
              {hasOpen ? `$${totalMargin.toFixed(0)}` : "—"}
            </p>
            <p className="text-[10px] text-neutral-600 font-semibold mt-1">Total Margin</p>
            <p className="text-[9px] text-neutral-400">semua {openPos.length} posisi</p>
          </div>

          {/* Closed Today */}
          <div className="bg-neutral-50 rounded-xl p-3">
            <p className="text-xl font-black tabular-nums text-blue-600">
              {learning?.monitor?.closed_today ?? 0}
            </p>
            <p className="text-[10px] text-neutral-600 font-semibold mt-1">Tutup Hari Ini</p>
            <p className="text-[9px] text-neutral-400">posisi closed hari ini</p>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-blue-50 border border-blue-200">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-[10px] font-bold text-blue-700">LIVE</span>
          <span className="text-[10px] text-blue-600 tabular-nums">{countdown}s</span>
        </div>
        <button onClick={onRefresh} className="text-xs text-teal-600 hover:text-teal-500 font-semibold">↺ Refresh</button>
      </div>
    </div>
  );
}
