"use client";
import { fmtPrice, fmtVol } from "@/lib/format";
import { PctBadge } from "@/components/ui/trading-badges";
import { type SpotCoin, fmtChangeColor } from "./types";

interface Props {
  c:    SpotCoin;
  rank: number;
  mode?: "default" | "volume";
  maxVol?: number;
}

export function SpotCoinRow({ c, rank, mode = "default", maxVol }: Props) {
  return (
    <div className="flex items-center gap-3 px-5 py-3 hover:bg-neutral-50 border-b border-neutral-100 last:border-0">
      <span className="text-sm font-black text-neutral-300 w-6 shrink-0">{rank}</span>
      {mode === "volume" && maxVol && (
        <div className="w-16 shrink-0">
          <div className="h-1.5 bg-neutral-100 rounded-full overflow-hidden">
            <div className="bg-blue-400 h-full rounded-full"
              style={{ width: `${Math.min((c.quote_vol_24h / maxVol) * 100, 100)}%` }} />
          </div>
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="font-bold text-sm">{c.base}
            <span className="text-neutral-400 font-normal text-xs">/USDT</span>
          </span>
        </div>
        <p className="text-[10px] text-neutral-400">
          H: ${fmtPrice(c.high_24h)} · L: ${fmtPrice(c.low_24h)} · {c.trades_24h.toLocaleString("en-US")} trades
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="font-mono font-bold text-sm">${fmtPrice(c.last_price)}</p>
        {mode === "volume"
          ? <><p className="font-bold text-sm text-blue-700">${fmtVol(c.quote_vol_24h)}</p><PctBadge pct={c.change_pct} /></>
          : <p className={`text-base font-black tabular-nums ${fmtChangeColor(c.change_pct)}`}>
              {c.change_pct >= 0 ? "+" : ""}{c.change_pct.toFixed(2)}%
            </p>
        }
      </div>
    </div>
  );
}

export function HeatTile({ c }: { c: SpotCoin }) {
  const volNorm = Math.sqrt(c.quote_vol_24h);
  const size = Math.max(48, Math.min(96, volNorm / 8000));
  const pct = c.change_pct;
  const bg =
    pct >= 15  ? "bg-green-600 text-white" :
    pct >= 8   ? "bg-green-500 text-white" :
    pct >= 3   ? "bg-green-400 text-white" :
    pct >= 0   ? "bg-green-100 text-green-800" :
    pct >= -3  ? "bg-red-100 text-red-700" :
    pct >= -8  ? "bg-red-400 text-white" :
    pct >= -15 ? "bg-red-500 text-white" :
                 "bg-red-700 text-white";

  return (
    <div
      title={`${c.symbol}\n${c.change_pct >= 0 ? "+" : ""}${c.change_pct.toFixed(2)}%\nVol $${fmtVol(c.quote_vol_24h)}`}
      className={`${bg} rounded-lg flex flex-col items-center justify-center cursor-default transition-transform hover:scale-105`}
      style={{ width: size, height: size, fontSize: Math.max(8, size / 6) }}
    >
      <span className="font-black leading-tight text-center px-0.5 truncate w-full text-center">
        {c.base}
      </span>
      <span className="font-bold leading-none">
        {pct >= 0 ? "+" : ""}{pct.toFixed(1)}%
      </span>
    </div>
  );
}
