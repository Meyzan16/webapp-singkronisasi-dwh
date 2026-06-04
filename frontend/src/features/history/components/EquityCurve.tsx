"use client";
import { useMemo } from "react";
import type { EquityPoint } from "@/types/history";

interface EquityCurveProps { points: EquityPoint[]; }

const W = 800;
const H = 220;
const PAD = { top: 16, right: 16, bottom: 32, left: 56 };

export function EquityCurve({ points }: EquityCurveProps) {
  const data = useMemo(() => {
    if (points.length < 2) return null;

    const pnls = points.map(p => p.pnl);
    const tss  = points.map(p => p.ts);
    const minP = Math.min(...pnls, 0);
    const maxP = Math.max(...pnls, 0);
    const minT = Math.min(...tss);
    const maxT = Math.max(...tss);

    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top  - PAD.bottom;
    const rangeP = maxP - minP || 1;
    const rangeT = maxT - minT || 1;

    const toX = (ts: number)  => PAD.left + ((ts  - minT) / rangeT) * innerW;
    const toY = (pnl: number) => PAD.top  + ((maxP - pnl) / rangeP) * innerH;

    const zeroY = toY(0);

    // Build SVG path
    const pts = points.map(p => `${toX(p.ts).toFixed(1)},${toY(p.pnl).toFixed(1)}`);
    const linePath = `M ${pts.join(" L ")}`;

    // Area fill (split above/below zero)
    const firstX = toX(points[0].ts);
    const lastX  = toX(points[points.length - 1].ts);
    const areaPath = `M ${firstX.toFixed(1)},${zeroY.toFixed(1)} L ${pts.join(" L ")} L ${lastX.toFixed(1)},${zeroY.toFixed(1)} Z`;

    // Y axis ticks (5 levels)
    const yTicks = Array.from({ length: 5 }, (_, i) => {
      const pnl = minP + (rangeP * i) / 4;
      return { y: toY(pnl), label: `${pnl >= 0 ? "+" : ""}${pnl.toFixed(1)}%` };
    });

    // X axis ticks (date labels — 4 evenly spaced)
    const xIdxs = [0, Math.floor(points.length * 0.33), Math.floor(points.length * 0.66), points.length - 1];
    const xTicks = xIdxs.map(i => ({
      x: toX(points[i].ts),
      label: new Date(points[i].ts).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    }));

    const lastPnl  = points[points.length - 1].pnl;
    const isProfit = lastPnl >= 0;

    return { linePath, areaPath, zeroY, yTicks, xTicks, lastPnl, isProfit };
  }, [points]);

  if (!data || points.length < 2) {
    return (
      <div className="flex items-center justify-center h-[220px] text-neutral-400 text-sm">
        <div className="text-center">
          <p className="text-3xl mb-2">📈</p>
          <p>Belum ada data — buka Scanner untuk mulai scan</p>
          <p className="text-xs mt-1 opacity-60">Setiap scan otomatis mencatat paper trade</p>
        </div>
      </div>
    );
  }

  const { linePath, areaPath, zeroY, yTicks, xTicks, lastPnl, isProfit } = data;
  const lineColor = isProfit ? "#10b981" : "#ef4444";
  const fillColor = isProfit ? "#10b98122" : "#ef444422";

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-xs text-neutral-500 font-semibold uppercase tracking-wider">Equity Curve</p>
          <p className="text-[10px] text-neutral-400">Simulasi 1% risk per trade · TP/SL dari harga real Binance</p>
        </div>
        <div className={`text-right ${isProfit ? "text-green-600" : "text-red-500"}`}>
          <p className="text-2xl font-black">{isProfit ? "+" : ""}{lastPnl.toFixed(1)}%</p>
          <p className="text-[10px] text-neutral-400">kumulatif</p>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ height: H }}
        preserveAspectRatio="none"
      >
        {/* Zero line */}
        <line
          x1={PAD.left} y1={zeroY}
          x2={W - PAD.right} y2={zeroY}
          stroke="#6b7280" strokeWidth="1" strokeDasharray="4 4"
        />

        {/* Y grid lines + labels */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line x1={PAD.left} y1={t.y} x2={W - PAD.right} y2={t.y}
              stroke="#f3f4f6" strokeWidth="0.5" />
            <text x={PAD.left - 6} y={t.y + 4} textAnchor="end"
              fontSize="10" fill="#9ca3af">{t.label}</text>
          </g>
        ))}

        {/* X axis labels */}
        {xTicks.map((t, i) => (
          <text key={i} x={t.x} y={H - 4} textAnchor="middle"
            fontSize="10" fill="#9ca3af">{t.label}</text>
        ))}

        {/* Area fill */}
        <path d={areaPath} fill={fillColor} />

        {/* Line */}
        <path d={linePath} fill="none" stroke={lineColor} strokeWidth="2.5"
          strokeLinecap="round" strokeLinejoin="round" />

        {/* Last point dot */}
        {(() => {
          const last = points[points.length - 1];
          const lx = PAD.left + ((last.ts - Math.min(...points.map(p => p.ts))) / (Math.max(...points.map(p => p.ts)) - Math.min(...points.map(p => p.ts)) || 1)) * (W - PAD.left - PAD.right);
          const ly = PAD.top + ((Math.max(...points.map(p => p.pnl), 0) - last.pnl) / (Math.max(...points.map(p => p.pnl), 0) - Math.min(...points.map(p => p.pnl), 0) || 1)) * (H - PAD.top - PAD.bottom);
          return <circle cx={lx} cy={ly} r="5" fill={lineColor} stroke="white" strokeWidth="2" />;
        })()}
      </svg>
    </div>
  );
}
