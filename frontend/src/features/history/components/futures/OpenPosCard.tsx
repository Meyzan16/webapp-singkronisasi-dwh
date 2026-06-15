"use client";
import { fmtPrice } from "@/lib/format";
import { DirBadge, RiskStatusBadge, PnlText } from "@/components/ui/trading-badges";
import { type FuturesPosition, type RiskPosition, calcNotional, calcMargin, calcLiqPrice, tradePnlDollar } from "./types";

export function OpenPosCard({ p, risk, riskDollar }: {
  p: FuturesPosition; risk?: RiskPosition; riskDollar: number;
}) {
  const notional = risk?.notional  ?? calcNotional(p.risk_pct, riskDollar);
  const margin   = risk?.margin    ?? calcMargin(notional, p.leverage);
  const liq      = risk?.liq_price ?? calcLiqPrice(p.entry, p.leverage, p.direction);
  const upnl$    = risk?.upnl_dollar ?? tradePnlDollar(p, riskDollar);
  const upnlPct  = p.unrealized_pnl;
  const rStatus  = risk?.risk_status ?? "SAFE";

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
        {risk?.trail_active && <span className="text-[9px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">Trail✓</span>}
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

      <div className="flex gap-1.5 mb-2 text-[10px]">
        <div className="flex-1 bg-red-50 border border-red-100 rounded-lg px-2 py-1">
          <span className="text-red-400 font-semibold">SL </span>
          <span className="font-mono text-red-600">${fmtPrice(p.sl)}</span>
          <span className="text-red-300 ml-1">-{p.risk_pct.toFixed(1)}%</span>
        </div>
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
            {risk ? `${risk.liq_dist_pct.toFixed(1)}%` : "—"}
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
    </div>
  );
}
