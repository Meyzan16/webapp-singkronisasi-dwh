"use client";
import { fmtPrice } from "@/lib/format";
import { DirBadge, TypeBadge } from "@/components/ui/trading-badges";
import { SectionPanel } from "@/components/ui/section-panel";
import { EmptyState } from "@/components/ui/feedback";
import { laneForSpot, openReason } from "@/lib/lanes";

interface OppPos {
  id: number; symbol: string; entry: number;
  current_price: number | null; unrealized_pnl_pct: number | null;
  tp1_hit: boolean; signals: string[]; position_size?: number | null; risk_dollar?: number | null;
  // PLAN_v8 P2/P5 — lane + open-reason
  alert_type?: string | null; entry_mode?: string | null; manual?: boolean; score?: number | null;
}

interface FutPos {
  id: number; symbol: string; direction: "LONG" | "SHORT"; agent: string;
  entry: number; current_price: number | null;
  unrealized_pnl: number | null; unrealized_pnl_dollar: number | null; leverage: number;
}

function UnrealizedBadge({ pct, dollar }: { pct: number | null; dollar?: number | null }) {
  if (pct == null) return <span className="text-neutral-400 text-xs">—</span>;
  const positive = pct >= 0;
  return (
    <div className={`text-right px-1.5 py-0.5 rounded ${positive ? "text-green-700 bg-green-50" : "text-red-600 bg-red-50"}`}>
      <p className="text-xs font-black tabular-nums leading-tight">
        {positive ? "+" : ""}{pct.toFixed(2)}%
      </p>
      {dollar != null && (
        <p className="text-[9px] font-semibold tabular-nums leading-tight opacity-80">
          {positive ? "+" : ""}${Math.abs(dollar).toFixed(2)}
        </p>
      )}
    </div>
  );
}

function PositionRow({ symbol, badges, sub, entry, currentPrice, pnlBadge }: {
  symbol: string; badges: React.ReactNode; sub: string;
  entry: number; currentPrice: number | null; pnlBadge: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-neutral-50">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-bold text-sm">{symbol.replace("USDT", "")}</span>
          {badges}
        </div>
        <p className="text-[10px] text-neutral-400 truncate">{sub}</p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-xs font-mono font-bold">${fmtPrice(entry)}</p>
        {currentPrice != null && <p className="text-[10px] text-neutral-400">→ ${fmtPrice(currentPrice)}</p>}
      </div>
      <div className="shrink-0 w-16 text-right">{pnlBadge}</div>
    </div>
  );
}

export function OpenPositionsPanel({ oppOpen, futOpen }: { oppOpen: OppPos[]; futOpen: FutPos[] }) {
  const total = oppOpen.length + futOpen.length;
  const badge = (
    <span className="text-[10px] bg-blue-100 text-blue-700 font-bold px-2 py-0.5 rounded-full">{total}</span>
  );

  return (
    <SectionPanel title="📍 Posisi Terbuka" badge={badge} action={{ label: "Lihat semua", href: "/history" }}>
      {total === 0 ? (
        <EmptyState title="Tidak ada posisi terbuka" />
      ) : (
        <div className="divide-y divide-neutral-100 max-h-72 overflow-y-auto">
          {oppOpen.map(p => {
            const lane = laneForSpot(p.alert_type, p.entry_mode);
            return (
              <PositionRow key={`o-${p.id}`}
                symbol={p.symbol}
                badges={<>
                  <TypeBadge type="spot" />
                  {/* PLAN_v8 P2: lane badge — jelas dari lane mana (BigMover/Accum/…) */}
                  <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${lane.badge}`}>{lane.emoji} {lane.label}</span>
                  {/* PLAN_v8 P5: force-open marker */}
                  {p.manual && <span className="text-[9px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-bold">🖐 Manual</span>}
                  {p.tp1_hit && <span className="text-[9px] bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded font-bold">TP1✓</span>}
                </>}
                // PLAN_v8 P2: sub kini menjelaskan ALASAN buka + score, bukan sinyal mentah
                sub={`${openReason(p.alert_type, p.entry_mode, p.manual)}${p.score != null ? ` · score ${Math.round(p.score)}` : ""}${
                  p.position_size != null ? ` · ~$${p.position_size.toFixed(0)}` : ""}`}
                entry={p.entry}
                currentPrice={p.current_price}
                pnlBadge={<UnrealizedBadge pct={p.unrealized_pnl_pct} />}
              />
            );
          })}
          {futOpen.map(p => {
            const agentShort = p.agent === "futures_agent1" ? "Pre" : p.agent === "futures_agent3" ? "Momo" : "Accum";
            return (
              <PositionRow key={`f-${p.id}`}
                symbol={p.symbol}
                badges={<>
                  <DirBadge dir={p.direction} size="xs" />
                  <span className="text-[9px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-bold">{agentShort} {p.leverage}x</span>
                </>}
                sub=""
                entry={p.entry}
                currentPrice={p.current_price}
                pnlBadge={<UnrealizedBadge pct={p.unrealized_pnl} dollar={p.unrealized_pnl_dollar} />}
              />
            );
          })}
        </div>
      )}
    </SectionPanel>
  );
}
