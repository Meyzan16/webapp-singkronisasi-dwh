"use client";
import { useCallback, useEffect, useState } from "react";

// PLAN-SIGNAL-GAP P4: informational panel — shows coins with big 24h moves and
// WHY they did/didn't qualify for a position, instead of just silently dropping them.

interface BigMoverMatch {
  agent:     string;
  direction: "LONG" | "SHORT";
  score:     number;
}

interface BigMover {
  symbol:     string;
  change_24h: number;
  status:     "lolos" | "tidak_lolos";
  reason:     string;
  matches:    BigMoverMatch[];
}

const AGENT_LABEL: Record<string, string> = {
  futures_agent1: "Pre-Gainer",
  futures_agent2: "Accumulation",
  futures_agent3: "Momentum",
};

export function BigMoversPanel() {
  const [movers, setMovers]   = useState<BigMover[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen]       = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/futures/big-movers?limit=60");
      if (r.ok) {
        const d = await r.json() as { movers: BigMover[] };
        setMovers(d.movers ?? []);
      }
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 60_000);
    return () => clearInterval(t);
  }, [refresh]);

  if (loading && movers.length === 0) return null;
  if (movers.length === 0) return null;

  const lolos     = movers.filter(m => m.status === "lolos");
  const tidakLolos = movers.filter(m => m.status === "tidak_lolos");

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
      <button onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between gap-2 px-4 py-3 hover:bg-neutral-50 transition-colors">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-neutral-700">📡 Big Movers Monitor</span>
          <span className="text-[10px] bg-neutral-100 text-neutral-500 px-2 py-0.5 rounded-full font-semibold">
            {movers.length} koin ≥10% 24h
          </span>
          {lolos.length > 0 && (
            <span className="text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-semibold">
              {lolos.length} lolos
            </span>
          )}
        </div>
        <span className={`text-neutral-400 transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
      </button>

      {open && (
        <div className="border-t border-neutral-100 px-4 py-3 space-y-3 max-h-96 overflow-y-auto">
          <p className="text-[10px] text-neutral-400">
            Daftar koin yang naik/turun besar dalam 24h, beserta status scoring — informasional, tidak auto-open posisi.
          </p>

          {lolos.length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-green-600 uppercase tracking-wider mb-1.5">✅ Lolos Scoring</p>
              <div className="space-y-1">
                {lolos.map(m => (
                  <div key={m.symbol} className="flex items-center gap-2 text-xs bg-green-50 border border-green-100 rounded-lg px-3 py-1.5">
                    <span className="font-bold w-20 shrink-0">{m.symbol.replace("USDT", "")}</span>
                    <span className={`font-mono font-semibold w-16 shrink-0 ${m.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
                      {m.change_24h >= 0 ? "+" : ""}{m.change_24h.toFixed(1)}%
                    </span>
                    <div className="flex gap-1 flex-wrap">
                      {m.matches.map((mt, i) => (
                        <span key={i} className="text-[9px] bg-white border border-green-200 text-green-700 px-1.5 py-0.5 rounded font-semibold">
                          {AGENT_LABEL[mt.agent] ?? mt.agent} {mt.direction} · {mt.score}pt
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {tidakLolos.length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-1.5">⏸ Belum Lolos</p>
              <div className="space-y-1">
                {tidakLolos.map(m => (
                  <div key={m.symbol} className="flex items-center gap-2 text-xs bg-neutral-50 border border-neutral-100 rounded-lg px-3 py-1.5">
                    <span className="font-bold w-20 shrink-0">{m.symbol.replace("USDT", "")}</span>
                    <span className={`font-mono font-semibold w-16 shrink-0 ${m.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
                      {m.change_24h >= 0 ? "+" : ""}{m.change_24h.toFixed(1)}%
                    </span>
                    <span className="text-[10px] text-neutral-400 flex-1 min-w-0 truncate">{m.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
