"use client";
import { fmtPrice } from "@/lib/format";
import { laneForSpot } from "@/lib/lanes";
import type { OppPosition } from "./OppSpotTypes";

interface OpenPositionCardProps {
  position:   OppPosition;
  riskDollar: number;
  closingId:  number | null;
  onClose:    (id: number, symbol: string) => void;
}

export function OpenPositionCard({
  position: p, riskDollar, closingId, onClose,
}: OpenPositionCardProps) {
  const upnl      = p.unrealized_pnl_pct;
  const upnlColor = upnl == null
    ? "text-neutral-400 bg-neutral-100 border-neutral-200"
    : upnl >= 0
      ? "text-green-700 bg-green-100 border-green-200"
      : "text-red-600 bg-red-100 border-red-200";

  const riskPct   = p.risk_pct > 0 ? p.risk_pct : 2.0;
  const notional$ = p.position_size ?? (riskDollar / (riskPct / 100));
  const maxLoss$  = p.risk_dollar ?? riskDollar;
  const conf      = p.confidence > 0
    ? p.confidence
    : Math.min(85, Math.round(40 + Math.max(0, p.score - 30) * 0.75));
  const tp1Prob   = Math.min(85, conf);
  const tp2Prob   = Math.round(tp1Prob * 0.65);
  const lane      = laneForSpot(p.alert_type, p.entry_mode);   // PLAN_v9 G3

  // PLAN_v10 — dynamic profit ladder
  const banked     = p.banked_dollar ?? 0;
  const runnerPct  = Math.round((p.remaining_fraction ?? 1) * 100);
  const ladder     = p.ladder ?? [];
  const isRunner   = !!p.is_runner;

  return (
    <div className="px-4 py-3 hover:bg-blue-50/50">
      {/* Row 1: symbol + unrealized PnL + close button */}
      <div className="flex items-center gap-3 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-sm">
              {p.symbol.replace("USDT", "")}/USDT
            </span>
            <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-semibold">
              LONG SPOT
            </span>
            {/* PLAN_v9 G3a — badge lane: jelas dari lane mana posisi ini */}
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${lane.badge}`} title={`Auto-open lane ini ≥${lane.autoScore}`}>
              {lane.emoji} {lane.label}
            </span>
            {/* PLAN_v9 G3b — bedakan force-open manual dari auto */}
            {p.manual && (
              <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-bold" title="Dibuka manual via Force-Open (bypass threshold)">
                🖐 Manual
              </span>
            )}
            <span className="text-[10px] bg-neutral-100 text-neutral-600 px-1.5 py-0.5 rounded font-mono"
              title={p.manual ? "Force-open manual" : `Auto-open ${lane.label} ≥${lane.autoScore}`}>
              Score {p.score}{!p.manual ? ` / ≥${lane.autoScore}` : ""}
            </span>
            {/* PLAN_v10 — runner aktif: ride sampai TP-n */}
            {isRunner ? (
              <span className="text-[10px] bg-green-100 text-green-700 border border-green-300 px-2 py-0.5 rounded-full font-bold" title="Runner aktif — ride winner sampai struktur patah / gate merah">
                🏃 Riding · {runnerPct}% sisa
              </span>
            ) : p.tp1_hit && (
              <span className="text-[10px] bg-yellow-100 text-yellow-700 border border-yellow-300 px-2 py-0.5 rounded-full font-bold">
                🟡 TP1 Hit — {runnerPct}% riding
              </span>
            )}
          </div>
          <p className="text-[10px] text-neutral-500 truncate mt-0.5">
            {p.signals?.[0] ?? ""}
          </p>
        </div>

        <div className="shrink-0 text-right">
          <span className={`text-sm font-black tabular-nums px-2 py-0.5 rounded-lg border ${upnlColor}`}>
            {upnl == null ? "—" : `${upnl >= 0 ? "+" : ""}${upnl.toFixed(2)}%`}
          </span>
          <p className="text-[9px] text-neutral-400 mt-0.5">unrealized</p>
        </div>

        <button
          onClick={e => { e.stopPropagation(); onClose(p.id, p.symbol); }}
          disabled={closingId === p.id}
          className="shrink-0 text-[10px] text-neutral-400 hover:text-red-500 border border-neutral-200 hover:border-red-300 px-2 py-1 rounded-lg transition-colors disabled:opacity-40 font-semibold"
        >
          {closingId === p.id ? "..." : "Tutup"}
        </button>
      </div>

      {/* PLAN_v10 — ladder strip: profit yang sudah dikunci (tak bisa hilang) + rung */}
      {(banked > 0 || ladder.length > 0) && (
        <div className="mb-2 flex items-center gap-2 flex-wrap bg-green-50/70 border border-green-100 rounded-lg px-2.5 py-1.5">
          <span className="text-[10px] font-bold text-green-700">
            🔒 Locked: +${banked.toFixed(2)}
          </span>
          <span className="text-[9px] text-neutral-400">·</span>
          <span className="text-[10px] text-neutral-500">Runner {runnerPct}%</span>
          {ladder.length > 0 && (
            <>
              <span className="text-[9px] text-neutral-400">·</span>
              <div className="flex items-center gap-1 flex-wrap">
                {ladder.map((r, i) => (
                  <span key={i} className="text-[9px] bg-white border border-green-200 text-green-700 px-1.5 py-0.5 rounded font-semibold"
                    title={`${r.rung} @ $${fmtPrice(r.price)} — jual ${Math.round(r.frac * 100)}%`}>
                    {r.rung.toUpperCase()} +${r.pnl_dollar.toFixed(2)}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* Row 2: 4 info tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">

        {/* Entry / current price */}
        <div className="bg-white/70 rounded-xl p-2">
          <p className="text-[9px] text-neutral-400 font-semibold uppercase mb-1">
            Entry → Harga
          </p>
          <p className="text-xs font-mono font-bold">${fmtPrice(p.entry)}</p>
          {p.current_price != null
            ? <p className="text-[10px] font-mono text-neutral-600">→ ${fmtPrice(p.current_price)}</p>
            : <p className="text-[10px] text-neutral-300">—</p>
          }
        </div>

        {/* Target / Stop */}
        <div className="bg-white/70 rounded-xl p-2">
          <p className="text-[9px] text-neutral-400 font-semibold uppercase mb-1">
            Target / Stop
          </p>
          {p.tp1 != null && p.tp1_pct > 0 && (
            <p className="text-[10px] text-green-500 font-semibold">TP1 +{p.tp1_pct.toFixed(1)}%</p>
          )}
          <p className="text-[10px] text-green-700 font-bold">TP2 +{p.tp2_pct.toFixed(1)}%</p>
          <p className="text-[10px] text-red-500 font-semibold">SL −{riskPct.toFixed(1)}%</p>
          <p className="text-[10px] text-neutral-400">R:R 1:{p.rr_ratio}</p>
        </div>

        {/* Modal spot */}
        <div className="bg-white/70 rounded-xl p-2">
          <p className="text-[9px] text-neutral-400 font-semibold uppercase mb-1">Modal Spot</p>
          <p className="text-sm font-black text-neutral-700">~${notional$.toFixed(0)}</p>
          <p className="text-[9px] text-neutral-500">dana terikat di posisi ini</p>
          <p className="text-[10px] text-red-500 font-semibold mt-0.5">
            Maks loss: <strong>${maxLoss$.toFixed(2)}</strong>
            <span className="text-neutral-400 font-normal"> jika SL</span>
          </p>
        </div>

        {/* Probability TP1/TP2 */}
        <div className="bg-white/70 rounded-xl p-2">
          <p className="text-[9px] text-neutral-400 font-semibold uppercase mb-1">
            Prob (estimasi)
          </p>
          {p.tp1 != null && p.tp1_pct > 0 && (
            <p className="text-[10px] font-bold text-green-600">TP1: ~{tp1Prob}%</p>
          )}
          <p className="text-[10px] font-bold text-green-500">TP2: ~{tp2Prob}%</p>
          <p className="text-[9px] text-neutral-400 mt-0.5">dari score {p.score}/100</p>
        </div>

      </div>
    </div>
  );
}
