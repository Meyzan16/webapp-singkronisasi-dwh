"use client";
import { fmtPrice, fmtRelTime } from "@/lib/format";
import { DirBadge, TypeBadge } from "@/components/ui/trading-badges";
import { SectionPanel } from "@/components/ui/section-panel";
import { EmptyState } from "@/components/ui/feedback";

export interface RecentTrade {
  id: string; symbol: string; type: "spot" | "fut"; dir: string;
  status: string; entry: number; pnl_pct: number | null; pnl$: number;
  agent?: string; leverage?: number; entry_at: number; closed_at: number | null;
  close_reason?: string | null;   // PLAN_v8 P2-B2
}

// PLAN_v8 P2-B2 — bedakan outcome ASLI (TP/SL murni) dari EXIT DIKELOLA
// (rotation, time-stop, breakeven, expiry). Sebelumnya semua ditulis tp/sl
// berdasar tanda pnl → owner tak bisa lihat mana kemenangan strategi murni.
const CLEAN_WIN  = new Set(["tp2_hit", "tp3_hit", "tp4_hit", "sl_plus"]);
const CLEAN_LOSS = new Set(["sl_hit", "sl_hit_fast_loop", "max_margin_loss",
  "flash_dump_exit", "flash_pump_exit", "liquidation", "liq_guard"]);

const REASON_LABEL: Record<string, string> = {
  urgent_rotation: "🔄 Rotasi", stagnant_rotation: "🔄 Rotasi",
  time_stop_scratch: "⏱ Time-stop", tp1_breakeven: "⚖ Breakeven",
  max_age_expired: "⏰ Expired", trend_reversal: "↩ Reversal",
  profit_protection: "🔒 Lock", flow_reversal: "↩ Flow", risk_adjusted: "✂ Cut",
};

function StatusPill({ status, reason }: { status: string; reason?: string | null }) {
  const r = reason || "";
  // exit dikelola → tampilkan label spesifik + warna netral (bukan menang/kalah strategi)
  const managed = r && !CLEAN_WIN.has(r) && !CLEAN_LOSS.has(r) && r !== "tp" && r !== "sl";
  if (managed) {
    return (
      <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full border bg-blue-50 text-blue-600 border-blue-200"
        title={`Exit dikelola: ${r} (tidak dihitung di WR bersih)`}>
        {REASON_LABEL[r] ?? "⚙ Dikelola"}
      </span>
    );
  }
  const win  = status === "tp";
  const loss = status === "sl";
  return (
    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${
      win  ? "bg-green-100 text-green-700 border-green-300" :
      loss ? "bg-red-100 text-red-600 border-red-300" :
             "bg-neutral-100 text-neutral-500 border-neutral-300"
    }`} title={r || status}>
      {win ? "✅ TP" : loss ? "🛑 SL" : "🤚"}
    </span>
  );
}

function agentShort(agent?: string) {
  if (!agent) return "";
  if (agent === "futures_agent1") return "Pre";
  if (agent === "futures_agent3") return "Momo";
  return "Accum";
}

export function RecentTradesPanel({ trades }: { trades: RecentTrade[] }) {
  return (
    <SectionPanel title="📋 Trade Terbaru (Spot + Futures)" action={{ label: "Lihat semua", href: "/history" }}>
      {trades.length === 0 ? (
        <EmptyState title="Belum ada trade tertutup" />
      ) : (
        <>
          <div className="hidden sm:grid grid-cols-[auto_1fr_auto_auto_auto_auto] gap-x-4 px-4 py-2 text-[10px] font-bold text-neutral-400 uppercase tracking-wider border-b border-neutral-100 bg-neutral-50">
            <span>Tipe</span><span>Koin</span><span className="text-right">Entry</span>
            <span className="text-right">P&L $</span><span className="text-right">P&L %</span><span className="text-right">Status</span>
          </div>
          <div className="divide-y divide-neutral-100">
            {trades.map(t => (
              <div key={t.id} className="grid grid-cols-[auto_1fr_auto_auto] sm:grid-cols-[auto_1fr_auto_auto_auto_auto] gap-x-4 items-center px-4 py-2.5 hover:bg-neutral-50">
                <div className="flex items-center gap-1">
                  <TypeBadge type={t.type === "spot" ? "spot" : "futures"} />
                  {t.type === "fut" && <DirBadge dir={t.dir as "LONG" | "SHORT"} size="xs" />}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-sm">{t.symbol.replace("USDT", "")}/USDT</span>
                    {t.type === "fut" && t.agent && (
                      <span className="text-[9px] text-neutral-400">
                        {agentShort(t.agent)}{t.leverage != null ? ` ${t.leverage}x` : ""}
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-neutral-400">{fmtRelTime(t.closed_at)}</p>
                </div>
                <div className="text-right hidden sm:block">
                  <p className="text-xs font-mono">${fmtPrice(t.entry)}</p>
                </div>
                <div className="text-right hidden sm:block">
                  <p className={`text-xs font-black tabular-nums ${t["pnl$"] >= 0 ? "text-green-600" : "text-red-500"}`}>
                    {t["pnl$"] >= 0 ? "+" : ""}${Math.abs(t["pnl$"]).toFixed(2)}
                  </p>
                </div>
                <div className="text-right">
                  {t.pnl_pct != null ? (
                    <span className={`text-xs font-black tabular-nums px-1.5 py-0.5 rounded ${t.pnl_pct >= 0 ? "text-green-700 bg-green-50" : "text-red-600 bg-red-50"}`}>
                      {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(1)}%
                    </span>
                  ) : <span className="text-neutral-300 text-xs">—</span>}
                </div>
                <div className="text-right">
                  <StatusPill status={t.status} reason={t.close_reason} />
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </SectionPanel>
  );
}
