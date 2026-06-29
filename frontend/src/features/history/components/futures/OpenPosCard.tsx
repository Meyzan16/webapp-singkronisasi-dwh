"use client";
import { useState } from "react";
import { fmtPrice } from "@/lib/format";
import { DirBadge, RiskStatusBadge, PnlText } from "@/components/ui/trading-badges";
import { type FuturesPosition, type RiskPosition, calcNotional, calcMargin, calcLiqPrice, tradePnlDollar } from "./types";

// PLAN_v2 P2.2 — ROI on margin (bukan notional) dengan threshold color.
function roiColorClass(roi: number | null | undefined): string {
  if (roi == null) return "text-neutral-400";
  if (roi >= 0)     return "text-green-600 font-bold";
  if (roi >= -50)   return "text-yellow-600 font-bold";
  if (roi >= -100)  return "text-red-500 font-bold";
  return "text-red-700 font-black animate-pulse";
}

export function OpenPosCard({ p, risk, riskDollar }: {
  p: FuturesPosition; risk?: RiskPosition; riskDollar: number;
}) {
  const [showEvents, setShowEvents] = useState(false);

  const notional    = risk?.notional  ?? calcNotional(p.risk_pct, riskDollar);
  const margin      = risk?.margin    ?? calcMargin(notional, p.leverage);
  const liq         = risk?.liq_price ?? calcLiqPrice(p.entry, p.leverage, p.direction);
  const upnl$       = risk?.upnl_dollar ?? tradePnlDollar(p, riskDollar);
  const upnlPct     = p.unrealized_pnl;
  const rStatus     = risk?.risk_status ?? "SAFE";
  const liqDistPct  = risk?.liq_dist_pct ?? (p.current_price != null ? Math.abs((p.current_price - liq) / liq * 100) : null);

  // PLAN_v2 P2.1 — ROI on margin: prefer server-computed, else derive from upnl$ + margin.
  const roi = risk?.roi_pct ?? (upnl$ != null && margin > 0 ? (upnl$ / margin) * 100 : null);
  const events = risk?.events ?? [];
  const [nowSec] = useState(() => Date.now() / 1000);
  const lastTickAge = risk?.last_tick_at != null
    ? Math.max(0, Math.round((nowSec - risk.last_tick_at)))
    : null;

  return (
    <div className={`rounded-xl border p-3 transition-all ${
      rStatus === "DANGER"  ? "border-red-300 bg-red-50" :
      rStatus === "WARNING" ? "border-yellow-200 bg-yellow-50" :
      "border-neutral-200 bg-white"
    }`}>
      <div className="flex items-center gap-1.5 mb-2 flex-wrap">
        <span className="font-bold text-sm">{p.symbol.replace("USDT", "")}</span>
        <DirBadge dir={p.direction} size="xs" />
        <span className="text-[9px] bg-neutral-100 text-neutral-600 px-1.5 py-0.5 rounded">{p.leverage}x</span>
        {risk?.auto_opened  && <span className="text-[9px] bg-teal-100 text-teal-700 px-1.5 py-0.5 rounded font-bold border border-teal-200">AUTO</span>}
        {risk?.trail_active && <span className="text-[9px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">Trailing</span>}
        <RiskStatusBadge status={rStatus} />
      </div>

      <div className="grid grid-cols-3 gap-1.5 mb-2 text-center">
        <div className="bg-neutral-50 rounded-lg px-2 py-1.5">
          <p className="text-[9px] text-neutral-400">Entry</p>
          <p className="text-xs font-mono font-bold">${fmtPrice(p.entry)}</p>
        </div>
        <div className="bg-neutral-50 rounded-lg px-2 py-1.5">
          <p className="text-[9px] text-neutral-400">Current</p>
          <p className={`text-xs font-mono font-bold ${upnl$ != null && upnl$ >= 0 ? "text-green-600" : "text-red-500"}`}>
            {p.current_price != null ? `$${fmtPrice(p.current_price)}` : "—"}
          </p>
        </div>
        <div className="bg-orange-50 rounded-lg px-2 py-1.5">
          <p className="text-[9px] text-orange-400">Liq ≈</p>
          <p className="text-xs font-mono font-bold text-orange-600">${fmtPrice(liq)}</p>
        </div>
      </div>

      <div className="flex gap-1 mb-2 text-[10px]">
        <div className="flex-1 bg-red-50 border border-red-100 rounded-lg px-2 py-1">
          <span className="text-red-400 font-semibold">SL </span>
          <span className="font-mono text-red-600">${fmtPrice(risk?.sl ?? p.sl)}</span>
          <span className="text-red-300 ml-1">-{(risk?.sl_dist_pct ?? p.risk_pct).toFixed(1)}%</span>
        </div>
        {(risk?.tp1 ?? p.tp1) != null && (
          <div className="flex-1 bg-yellow-50 border border-yellow-100 rounded-lg px-2 py-1">
            <span className="text-yellow-600 font-semibold">TP1 </span>
            <span className="font-mono text-yellow-700">${fmtPrice((risk?.tp1 ?? p.tp1)!)}</span>
          </div>
        )}
        <div className="flex-1 bg-green-50 border border-green-100 rounded-lg px-2 py-1">
          <span className="text-green-500 font-semibold">TP2 </span>
          <span className="font-mono text-green-700">${fmtPrice(p.tp2)}</span>
          <span className="text-green-400 ml-1">+{p.tp2_pct.toFixed(1)}%</span>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs">
        <span className="text-neutral-500">
          Margin <strong className="text-blue-600">${margin.toFixed(0)}</strong>
          <span className="mx-1 text-neutral-300">·</span>
          Liq dist <strong className={rStatus === "DANGER" ? "text-red-600" : rStatus === "WARNING" ? "text-yellow-600" : "text-neutral-700"}>
            {liqDistPct != null ? `${liqDistPct.toFixed(1)}%` : "—"}
          </strong>
        </span>
        <span>
          <PnlText value={upnl$} />
          {upnlPct != null && (
            <span className={`text-[10px] ml-1 ${upnlPct >= 0 ? "text-green-600" : "text-red-500"}`}>
              ({upnlPct >= 0 ? "+" : ""}{upnlPct.toFixed(2)}%)
            </span>
          )}
        </span>
      </div>

      {/* PLAN_v2 P2.1+P2.2 — ROI on margin (the number user actually cares about) */}
      <div className="mt-1.5 pt-1.5 border-t border-neutral-100 flex items-center justify-between text-[11px]">
        <span className="text-neutral-500">
          ROI{" "}
          <span className={roiColorClass(roi)}>
            {roi != null ? `${roi >= 0 ? "+" : ""}${roi.toFixed(1)}%` : "—"}
            {roi != null && roi < -100 && " ⚠"}
          </span>
        </span>
        {/* PLAN_v2 P1.4 — last monitor tick proof */}
        <button
          type="button"
          onClick={() => setShowEvents(s => !s)}
          className="text-[10px] text-neutral-400 hover:text-neutral-600"
          title={risk?.last_tick_event ?? "tick"}
        >
          {lastTickAge != null
            ? `🩺 ${lastTickAge < 60 ? `${lastTickAge}s` : `${Math.round(lastTickAge/60)}m`} ago`
            : "🩺 —"}
          {events.length > 0 && (
            <span className="ml-1 text-blue-500">· {events.length} evt</span>
          )}
        </button>
      </div>

      {/* PLAN_v2 P2.4 — event timeline drawer */}
      {showEvents && events.length > 0 && (
        <div className="mt-1.5 pt-1.5 border-t border-neutral-100 space-y-0.5">
          {events.slice().reverse().map((ev, i) => (
            <div key={i} className="flex items-center justify-between text-[9px] font-mono">
              <span className="text-blue-600">{ev.kind}</span>
              <span className="text-neutral-400">
                {new Date(Number(ev.ts) * 1000).toLocaleTimeString("id-ID")}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* G6+G15: cumulative cost display */}
      {((risk?.cumulative_funding_paid ?? 0) > 0 || (risk?.cumulative_fee_paid ?? 0) > 0) && (
        <div className="mt-1.5 pt-1.5 border-t border-neutral-100 flex items-center justify-between text-[9px] text-neutral-400">
          <span>Costs (funding + fee)</span>
          <span className="font-semibold text-orange-500">
            −${((risk?.cumulative_funding_paid ?? 0) + (risk?.cumulative_fee_paid ?? 0)).toFixed(3)}
            {risk?.peak_pnl_pct != null && risk.peak_pnl_pct > 0 && (
              <span className="ml-1 text-neutral-400">· peak {risk.peak_pnl_pct.toFixed(1)}%</span>
            )}
          </span>
        </div>
      )}
    </div>
  );
}
