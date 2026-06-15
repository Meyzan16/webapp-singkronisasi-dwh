"use client";
import { useRouter } from "next/navigation";
import { fmtPrice, fmtVol } from "@/lib/format";
import { PctBadge } from "@/components/ui/trading-badges";
import { type Coin, fmtFundingColor, fmtDate, fmtBg } from "./types";

export function FundingBadge({ fr }: { fr: number }) {
  const sign = fr > 0 ? "+" : "";
  return (
    <span className={`text-[9px] font-black tabular-nums px-1 py-0.5 rounded ${fmtFundingColor(fr)}`}
      title={`Funding Rate: ${sign}${fr.toFixed(4)}%`}>
      FR {sign}{fr.toFixed(3)}%
    </span>
  );
}

export function CoinRow({ c, rank, showNew, showFR }: { c: Coin; rank: number; showNew?: boolean; showFR?: boolean }) {
  const router = useRouter();
  return (
    <div
      onClick={() => router.push(`/scanner?symbol=${c.base}`)}
      title={`Scan ${c.base} di Pre-Gainer Scanner`}
      className="flex items-center gap-2 px-3 py-2 hover:bg-neutral-50 border-b border-neutral-100 last:border-0 cursor-pointer">
      <span className="text-[10px] text-neutral-400 w-5 shrink-0 tabular-nums">{rank}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-bold text-sm">{c.base}</span>
          <span className="text-[9px] text-neutral-400">/USDT</span>
          {showNew && c.is_new && (
            <span className="text-[8px] font-black bg-teal-500 text-white px-1 rounded">NEW</span>
          )}
          {showFR && <FundingBadge fr={c.funding_rate} />}
          {c.agent1_score != null && c.agent1_score >= 52 && (
            <span className="text-[8px] font-black bg-blue-100 text-blue-700 px-1 rounded" title="Skor Agent 1 Pre-Gainer">
              🎯 {c.agent1_score.toFixed(0)}
            </span>
          )}
        </div>
        <p className="text-[9px] text-neutral-400 tabular-nums">
          Vol ${fmtVol(c.quote_vol_24h)} · {c.trades_24h.toLocaleString("en-US")} trades
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-xs font-mono font-bold">${fmtPrice(c.last_price)}</p>
        <PctBadge pct={c.change_pct} />
      </div>
    </div>
  );
}

export function NewListingCard({ c }: { c: Coin }) {
  const age = c.days_listed !== null ? (c.days_listed === 0 ? "Hari ini!" : `${c.days_listed} hari lalu`) : "—";
  const isVeryNew = c.days_listed !== null && c.days_listed <= 7;
  return (
    <div className={`rounded-xl border p-3 hover:shadow-md transition-all ${
      isVeryNew ? "border-teal-300 bg-teal-50" : "border-neutral-200 bg-white"
    }`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className="flex items-center gap-1.5">
            <span className="font-bold text-base">{c.base}</span>
            <span className="text-[9px] text-neutral-400">/USDT PERP</span>
            {isVeryNew && (
              <span className="text-[9px] font-black bg-teal-500 text-white px-1.5 py-0.5 rounded-full animate-pulse">🔥 NEW</span>
            )}
          </div>
          <p className="text-[10px] text-neutral-400 mt-0.5">Listed: {fmtDate(c.onboard_date)} · {age}</p>
        </div>
        <PctBadge pct={c.change_pct} />
      </div>
      <div className="grid grid-cols-2 gap-1.5 text-center mb-2">
        <div className="bg-white/70 rounded-lg px-2 py-1">
          <p className="text-[9px] text-neutral-400">Harga</p>
          <p className="text-xs font-mono font-bold">${fmtPrice(c.last_price)}</p>
        </div>
        <div className="bg-white/70 rounded-lg px-2 py-1">
          <p className="text-[9px] text-neutral-400">Volume</p>
          <p className="text-xs font-mono font-bold">${fmtVol(c.quote_vol_24h)}</p>
        </div>
      </div>
      <div className="flex justify-center">
        <FundingBadge fr={c.funding_rate} />
      </div>
    </div>
  );
}

export function HeatTile({ c }: { c: Coin }) {
  const router = useRouter();
  const size = Math.min(Math.max(c.quote_vol_24h / 50_000_000, 0.5), 3.0);
  return (
    <div
      onClick={() => router.push(`/scanner?symbol=${c.base}`)}
      title={`${c.symbol}: ${c.change_pct >= 0 ? "+" : ""}${c.change_pct.toFixed(2)}% | Vol $${fmtVol(c.quote_vol_24h)} | FR ${c.funding_rate >= 0 ? "+" : ""}${c.funding_rate.toFixed(3)}% — klik untuk scan`}
      className={`rounded-lg flex flex-col items-center justify-center cursor-pointer transition-all hover:scale-105 ${fmtBg(c.change_pct)}`}
      style={{ padding: `${6 * size}px ${4 * size}px`, minHeight: `${36 * size}px` }}
    >
      <p className={`font-bold leading-tight ${size > 1.5 ? "text-sm" : "text-[10px]"}`}>{c.base}</p>
      <p className={`font-black tabular-nums ${size > 1.5 ? "text-base" : "text-[10px]"}`}>
        {c.change_pct >= 0 ? "+" : ""}{c.change_pct.toFixed(1)}%
      </p>
    </div>
  );
}
