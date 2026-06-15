"use client";
import { fmtPrice } from "@/lib/format";
import { DirBadge, TypeBadge } from "@/components/ui/trading-badges";
import { SectionPanel } from "@/components/ui/section-panel";
import { EmptyState } from "@/components/ui/feedback";

interface OppPos {
  id: number; symbol: string; entry: number;
  current_price: number | null; unrealized_pnl_pct: number | null;
  tp1_hit: boolean; signals: string[]; position_size?: number | null; risk_dollar?: number | null;
}

interface FutPos {
  id: number; symbol: string; direction: "LONG" | "SHORT"; agent: string;
  entry: number; current_price: number | null; unrealized_pnl: number | null; leverage: number;
}

function UnrealizedBadge({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="text-neutral-400 text-xs">—</span>;
  return (
    <span className={`text-xs font-black tabular-nums px-1.5 py-0.5 rounded ${pct >= 0 ? "text-green-700 bg-green-50" : "text-red-600 bg-red-50"}`}>
      {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
    </span>
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
          {oppOpen.map(p => (
            <PositionRow key={`o-${p.id}`}
              symbol={p.symbol}
              badges={<>
                <TypeBadge type="spot" />
                {p.tp1_hit && <span className="text-[9px] bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded font-bold">TP1✓</span>}
              </>}
              sub={p.position_size != null
                ? `~$${p.position_size.toFixed(0)} · Risk $${(p.risk_dollar ?? 0).toFixed(1)}`
                : (p.signals[0] ?? "")}
              entry={p.entry}
              currentPrice={p.current_price}
              pnlBadge={<UnrealizedBadge pct={p.unrealized_pnl_pct} />}
            />
          ))}
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
                pnlBadge={<UnrealizedBadge pct={p.unrealized_pnl} />}
              />
            );
          })}
        </div>
      )}
    </SectionPanel>
  );
}
