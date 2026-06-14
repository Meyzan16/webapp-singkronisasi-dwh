"use client";
import { useCallback, useEffect, useState, useMemo, useRef } from "react";
import { fmtPrice } from "@/lib/format";
import { MarketIntelBanner } from "@/components/MarketIntelBanner";

// ── Types ─────────────────────────────────────────────────────────────────────

interface FuturesSignal {
  symbol:       string;
  direction:    "LONG" | "SHORT";
  price:        number;
  score:        number;
  signals:      string[];
  leverage:     number;
  change_24h:   number;
  funding_rate: number;
  oi_change:    number;
  liq_long:     number;
  liq_short:    number;
  agent:        string;
  entry:        number;
  sl:           number;
  tp1:          number;
  tp2:          number;
  tp3:          number;
  risk_pct:     number;
  tp1_pct:      number;   // P8: backend already sends these — were dropped before
  tp2_pct:      number;
  tp3_pct:      number;
  rr_ratio:     number;
}

interface OpenPosition {
  id:           number;
  symbol:       string;
  direction:    "LONG" | "SHORT";
  agent:        string;
  entry:        number;
  current:      number;
  upnl_pct:     number;
  upnl_dollar:  number;
  liq_dist_pct: number;
  risk_status:  "SAFE" | "WARNING" | "DANGER";
  margin:       number;
  leverage:     number;
  auto_opened:  boolean;
}

type ConnState = "connecting" | "connected" | "reconnecting" | "paused";
const INTERVAL_SEC  = 2 * 60;

// F111: derive WS URL from env or current host so non-localhost deployments connect
function futuresWsUrl(): string {
  const base = process.env.NEXT_PUBLIC_WS_URL;
  if (base) return `${base}/ws/futures`;
  if (typeof window !== "undefined") return `ws://${window.location.host}/ws/futures`;
  return "ws://localhost:8000/ws/futures";
}

const CONN_META: Record<ConnState, { dot: string; label: string; color: string }> = {
  connected:    { dot: "bg-green-400",               label: "LIVE",        color: "text-green-400 border-green-500/40 bg-green-500/10"   },
  connecting:   { dot: "bg-yellow-400 animate-pulse", label: "CONNECTING", color: "text-yellow-400 border-yellow-500/40 bg-yellow-500/10" },
  reconnecting: { dot: "bg-orange-400 animate-pulse", label: "RECONN...",  color: "text-orange-400 border-orange-500/40 bg-orange-500/10" },
  paused:       { dot: "bg-neutral-500",              label: "PAUSED",     color: "text-neutral-400 border-neutral-600 bg-neutral-700/50" },
};

// ── Sub-components ─────────────────────────────────────────────────────────────

function DirBadge({ dir }: { dir: "LONG" | "SHORT" }) {
  return dir === "LONG"
    ? <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-green-100 text-green-700 border border-green-300">▲ LONG</span>
    : <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-red-100 text-red-700 border border-red-300">▼ SHORT</span>;
}

function AgentBadge({ agent }: { agent: string }) {
  if (agent === "futures_agent1")
    return <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">Pre-Gainer</span>;
  if (agent === "futures_agent3")
    return <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-orange-100 text-orange-700">Momentum</span>;
  return <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">Accum.</span>;
}

function ScoreBubble({ score }: { score: number }) {
  const cls = score >= 80 ? "bg-green-500" : score >= 65 ? "bg-yellow-500" : "bg-neutral-400";
  return (
    <div className={`w-12 h-12 rounded-full ${cls} flex flex-col items-center justify-center shrink-0 shadow-sm`}>
      <span className="text-white text-sm font-black leading-none">{score.toFixed(0)}</span>
      <span className="text-white/60 text-[8px]">pt</span>
    </div>
  );
}

function SignalCard({ s, isNew, isOpen, openPos, onClick, autoThreshold }: {
  s: FuturesSignal; isNew: boolean; isOpen: boolean;
  openPos?: OpenPosition; onClick: () => void; autoThreshold: number
}) {
  const isLong = s.direction === "LONG";
  return (
    <div onClick={onClick}
      className={`rounded-2xl border-2 bg-white cursor-pointer hover:shadow-xl hover:-translate-y-0.5 transition-all duration-200
        ${isLong ? "border-green-200 hover:border-green-400" : "border-red-200 hover:border-red-400"}
        ${isNew ? "ring-2 ring-teal-400 ring-offset-1" : ""}
        ${isOpen ? "opacity-75" : ""}`}>
      {isNew && <div className={`h-0.5 rounded-t-2xl ${isLong ? "bg-green-400" : "bg-red-400"}`} />}
      <div className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-xl font-black">{s.symbol.replace("USDT", "")}</span>
              <span className="text-neutral-400 text-xs">/USDT</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <DirBadge dir={s.direction} />
              <AgentBadge agent={s.agent} />
              <span className="text-[10px] bg-neutral-100 text-neutral-600 px-1.5 py-0.5 rounded font-semibold">{s.leverage}x Cross</span>
              {isOpen && openPos && (
                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${
                  openPos.upnl_pct >= 0 ? "bg-green-100 text-green-700 border-green-200" : "bg-red-100 text-red-600 border-red-200"
                }`}>
                  OPEN {openPos.upnl_pct >= 0 ? "+" : ""}{openPos.upnl_pct.toFixed(1)}%
                </span>
              )}
              {s.score >= autoThreshold && (
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-teal-100 text-teal-700 border border-teal-200">
                  🤖 AUTO
                </span>
              )}
              <span className={`text-[10px] border px-1.5 py-0.5 rounded font-mono font-semibold ${s.funding_rate > 0.05 ? "text-red-600 bg-red-50 border-red-200" : s.funding_rate < -0.02 ? "text-green-600 bg-green-50 border-green-200" : "text-neutral-400 bg-neutral-50 border-neutral-200"}`}>
                F {s.funding_rate >= 0 ? "+" : ""}{s.funding_rate.toFixed(3)}%
              </span>
            </div>
          </div>
          <ScoreBubble score={s.score} />
        </div>

        {/* Price */}
        <div className="flex items-center justify-between bg-neutral-50 rounded-xl px-3 py-2">
          <div>
            <p className="text-[9px] text-neutral-400 uppercase tracking-wide font-semibold">Harga</p>
            <p className="text-base font-black font-mono">${fmtPrice(s.price)}</p>
          </div>
          <span className={`text-sm font-bold ${s.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
            {s.change_24h >= 0 ? "+" : ""}{s.change_24h.toFixed(1)}%
          </span>
        </div>

        {/* Signals */}
        <div className="space-y-1">
          {s.signals.slice(0, 3).map((sig, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full mt-[5px] shrink-0 ${isLong ? "bg-green-500" : "bg-red-500"}`} />
              <p className="text-[11px] text-neutral-600 leading-snug">{sig}</p>
            </div>
          ))}
        </div>

        {/* OI / Liq */}
        <div className="flex gap-1.5 flex-wrap">
          {s.oi_change !== 0 && (
            <span className={`text-[10px] border px-1.5 py-0.5 rounded font-semibold ${s.oi_change > 0 ? "text-teal-600 bg-teal-50 border-teal-200" : "text-orange-600 bg-orange-50 border-orange-200"}`}>
              OI {s.oi_change > 0 ? "+" : ""}{s.oi_change.toFixed(1)}%
            </span>
          )}
          {/* UI-8: liquidation feed is a directional PROXY (not real USDT) — show arah, no fake $ */}
          {s.liq_long > 0.1 && (
            <span className="text-[10px] text-red-600 bg-red-50 border border-red-200 px-1.5 py-0.5 rounded font-semibold" title="Proxy arah dari shift L/S-ratio, bukan USDT nyata">
              Liq L ▼ proxy
            </span>
          )}
          {s.liq_short > 0.1 && (
            <span className="text-[10px] text-green-600 bg-green-50 border border-green-200 px-1.5 py-0.5 rounded font-semibold" title="Proxy arah dari shift L/S-ratio, bukan USDT nyata">
              Liq S ▲ proxy
            </span>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-1 border-t border-neutral-100 text-[10px]">
          <span className={`font-bold ${isLong ? "text-green-600" : "text-red-500"}`}>
            R:R 1:{s.rr_ratio} · SL -{s.risk_pct}%
          </span>
          <span className="text-teal-600 font-bold">Buka Posisi →</span>
        </div>
      </div>
    </div>
  );
}

// ── Trade Modal ────────────────────────────────────────────────────────────────

function TradeModal({ s, onClose }: { s: FuturesSignal; onClose: () => void }) {
  const [opening, setOpening] = useState(false);
  const [opened,  setOpened]  = useState(false);
  const [error,   setError]   = useState("");
  const [balance, setBalance] = useState(1000);   // F38: fallback until /balance/futures loads
  const isLong = s.direction === "LONG";

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", h); document.body.style.overflow = ""; };
  }, [onClose]);

  // F38: fetch real paper balance for accurate position-sizing simulation
  useEffect(() => {
    void (async () => {
      try {
        const r = await fetch("/api/v1/balance/futures");
        if (r.ok) {
          const d = await r.json() as { balance?: number };
          if (typeof d.balance === "number" && d.balance > 0) setBalance(d.balance);
        }
      } catch { /* keep fallback */ }
    })();
  }, []);

  const handleOpen = async () => {
    setOpening(true); setError("");
    try {
      const res = await fetch("/api/v1/futures/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: s.symbol, direction: s.direction, agent: s.agent,
          entry: s.entry, sl: s.sl, tp1: s.tp1, tp2: s.tp2, tp3: s.tp3,
          risk_pct: s.risk_pct, tp1_pct: s.tp1_pct, tp2_pct: s.tp2_pct, tp3_pct: s.tp3_pct,
          rr_ratio: s.rr_ratio, leverage: s.leverage, score: s.score,
          signals: s.signals, funding_rate: s.funding_rate,
          oi_change: s.oi_change, liq_long: s.liq_long, liq_short: s.liq_short,
        }),
      });
      if (!res.ok) { const e = await res.json() as { detail?: string }; throw new Error(e.detail ?? "Gagal"); }
      setOpened(true);
    } catch (e) { setError((e as Error).message); }
    finally { setOpening(false); }
  };

  // P8: build the price ladder so the HIGHEST price is always at the top.
  // LONG: TP3>TP2>TP1>Entry>SL · SHORT: SL>Entry>TP1>TP2>TP3 (was inverted for SHORT).
  type Lvl = { label: string; val: number; pct: number | null; loss?: boolean; cl: string };
  const tpRows: Lvl[] = [
    { label: "TP3",   val: s.tp3, pct: s.tp3_pct, cl: "text-green-400" },
    { label: "TP2 ★", val: s.tp2, pct: s.tp2_pct, cl: "text-green-600 bg-green-50 font-bold" },
    { label: "TP1",   val: s.tp1, pct: s.tp1_pct, cl: "text-green-500" },
  ];
  const entryRow: Lvl = { label: "Entry", val: s.entry, pct: null, cl: "bg-neutral-100 font-bold" };
  const slRow:    Lvl = { label: "SL",    val: s.sl,    pct: s.risk_pct, loss: true, cl: "text-red-500" };
  const levels: Lvl[] = isLong
    ? [...tpRows, entryRow, slRow]                       // high → low
    : [slRow, entryRow, ...[...tpRows].reverse()];       // SHORT: SL(top) → TP3(bottom)

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white w-full sm:max-w-lg rounded-t-3xl sm:rounded-2xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col">
        <div className="flex justify-center pt-3 pb-1 sm:hidden"><div className="w-10 h-1 bg-neutral-300 rounded-full" /></div>

        {/* Header */}
        <div className={`p-5 pb-4 ${isLong ? "bg-gradient-to-br from-neutral-900 via-green-950 to-neutral-900" : "bg-gradient-to-br from-neutral-900 via-red-950 to-neutral-900"} text-white`}>
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <h2 className="text-3xl font-black">{s.symbol.replace("USDT", "")}</h2>
                <span className="text-neutral-400 text-lg self-end pb-0.5">/USDT</span>
              </div>
              <div className="flex gap-2 flex-wrap">
                <DirBadge dir={s.direction} />
                <span className="text-[11px] bg-white/10 text-white px-2 py-0.5 rounded font-bold">{s.leverage}x Cross Margin</span>
                <span className={`text-[11px] px-2 py-0.5 rounded font-bold border ${s.agent === "futures_agent1" ? "bg-blue-600/30 text-blue-300 border-blue-500/30" : s.agent === "futures_agent3" ? "bg-orange-600/30 text-orange-300 border-orange-500/30" : "bg-purple-600/30 text-purple-300 border-purple-500/30"}`}>
                  {s.agent === "futures_agent1" ? "Agent 1 — Pre-Gainer Scout" : s.agent === "futures_agent3" ? "Agent 3 — Momentum Capture" : "Agent 2 — Accumulation Detector"}
                </span>
              </div>
            </div>
            <div className="flex gap-2">
              <ScoreBubble score={s.score} />
              <button onClick={onClose} className="w-8 h-8 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center text-white">✕</button>
            </div>
          </div>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 p-5 space-y-4">

          {/* Levels */}
          <div>
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2">Level Posisi ({s.direction})</p>
            <div className="border border-neutral-100 rounded-2xl overflow-hidden">
              {levels.map(row => (
                <div key={row.label} className={`flex items-center gap-3 px-4 py-2 ${row.cl}`}>
                  <span className="text-[10px] font-mono w-12 shrink-0">{row.label}</span>
                  <span className="flex-1 font-mono text-sm tabular-nums">${fmtPrice(row.val)}</span>
                  {row.pct != null && (
                    <span className="text-[10px] font-mono tabular-nums opacity-80">
                      {row.loss ? "-" : "+"}{row.pct}%
                    </span>
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-2 mt-3 flex-wrap">
              {[
                { label: "R:R",     value: `1:${s.rr_ratio}`,  cls: "bg-green-100 border-green-200 text-green-700" },
                { label: "Risk SL", value: `-${s.risk_pct}%`,  cls: "bg-red-50 border-red-100 text-red-600"        },
                { label: "Target",  value: `+${s.tp2_pct}%`,   cls: "bg-green-50 border-green-100 text-green-600"  },
                { label: "Leverage",value: `${s.leverage}x`,    cls: "bg-blue-50 border-blue-100 text-blue-700"    },
              ].map(s => (
                <div key={s.label} className={`border rounded-xl px-3 py-2 text-center ${s.cls}`}>
                  <p className="text-[10px] font-semibold opacity-70">{s.label}</p>
                  <p className="text-lg font-black">{s.value}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Signals */}
          <div>
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2">Sinyal</p>
            <div className="space-y-2">
              {s.signals.map((sig, i) => (
                <div key={i} className="flex items-start gap-2 bg-neutral-50 rounded-xl px-3 py-2.5">
                  <span className={`w-2 h-2 rounded-full mt-1 shrink-0 ${isLong ? "bg-green-500" : "bg-red-500"}`} />
                  <p className="text-sm text-neutral-700">{sig}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Futures stats */}
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: "Funding",  value: `${s.funding_rate >= 0 ? "+" : ""}${s.funding_rate.toFixed(3)}%`, cls: s.funding_rate > 0.05 ? "text-red-500" : s.funding_rate < -0.02 ? "text-green-600" : "text-neutral-700" },
              { label: "OI Change",value: `${s.oi_change >= 0 ? "+" : ""}${s.oi_change.toFixed(1)}%`,       cls: s.oi_change > 2 ? "text-teal-600" : "text-neutral-700" },
              // P8: show the squeeze FUEL for the trade side — LONG feeds on short liq, SHORT on long liq
              { label: isLong ? "Short Liq 🔥" : "Long Liq 🔥", value: isLong ? `$${s.liq_short.toFixed(1)}M` : `$${s.liq_long.toFixed(1)}M`, cls: isLong ? "text-green-600" : "text-red-500" },
            ].map(x => (
              <div key={x.label} className="bg-neutral-50 rounded-xl p-3 text-center">
                <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold mb-0.5">{x.label}</p>
                <p className={`text-base font-black ${x.cls}`}>{x.value}</p>
              </div>
            ))}
          </div>

          {/* Position sizing simulation */}
          {!opened && (() => {
            const BALANCE  = balance;                                        // F38: real balance from API
            const riskDollar  = BALANCE * 0.01;                              // 1% of balance
            const notional    = s.risk_pct > 0 ? riskDollar / (s.risk_pct / 100) : 0;
            const margin      = s.leverage > 0 ? notional / s.leverage : notional;
            const winDollar   = riskDollar * s.rr_ratio;
            const liqDist     = s.entry * (0.95 / Math.max(s.leverage, 1));
            const liqPrice    = s.direction === "LONG" ? s.entry - liqDist : s.entry + liqDist;
            return (
              <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4">
                <p className="text-[10px] font-bold text-amber-700 uppercase tracking-wider mb-3">💰 Simulasi Position Sizing (${BALANCE.toLocaleString()} balance)</p>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { label: "Modal",      value: `$${BALANCE.toLocaleString()} USDT`, cls: "text-neutral-700" },
                    { label: "Risk (1%)",  value: `-$${riskDollar.toFixed(0)}`,   cls: "text-red-600"     },
                    { label: "Notional",   value: `$${notional.toFixed(0)}`,      cls: "text-neutral-700" },
                    { label: "Margin",     value: `$${margin.toFixed(0)}`,        cls: "text-blue-600"    },
                    { label: "Win Est.",   value: `+$${winDollar.toFixed(1)}`,    cls: "text-green-600"   },
                    { label: "Liq. Price", value: `$${liqPrice.toFixed(liqPrice > 100 ? 2 : 4)}`, cls: "text-orange-600" },
                  ].map(x => (
                    <div key={x.label} className="bg-white/60 rounded-xl px-3 py-2 flex items-center justify-between">
                      <span className="text-[10px] text-neutral-500 font-semibold">{x.label}</span>
                      <span className={`text-sm font-black tabular-nums ${x.cls}`}>{x.value}</span>
                    </div>
                  ))}
                </div>
                <p className="text-[9px] text-amber-600 mt-2 text-center">
                  Liq ≈ entry ± (95% / {s.leverage}x) — jauh dari SL ${(s.direction === "LONG" ? s.entry - s.sl : s.sl - s.entry).toFixed(liqDist > 10 ? 2 : 4)} risiko
                </p>
              </div>
            );
          })()}

          {/* Action */}
          {opened ? (
            <div className="bg-green-50 border border-green-200 rounded-2xl px-4 py-4 text-center">
              <p className="text-2xl mb-1">✅</p>
              <p className="font-bold text-green-700">Posisi {s.direction} berhasil dibuka!</p>
              <p className="text-xs text-green-600 mt-1">Lihat di <strong>History → Futures</strong></p>
              <button onClick={onClose} className="mt-3 text-xs bg-green-600 hover:bg-green-500 text-white font-semibold px-4 py-2 rounded-xl">Tutup</button>
            </div>
          ) : (
            <div className="space-y-2">
              {error && <p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2 text-center">{error}</p>}
              <button onClick={() => void handleOpen()} disabled={opening}
                className={`w-full font-bold py-4 rounded-2xl text-sm text-white disabled:opacity-40 flex items-center justify-center gap-2 ${isLong ? "bg-green-600 hover:bg-green-500" : "bg-red-600 hover:bg-red-500"}`}>
                {opening
                  ? <><span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />Membuka...</>
                  : <>{isLong ? "▲ Buka LONG" : "▼ Buka SHORT"} — {s.leverage}x Cross</>}
              </button>
              <button onClick={onClose} className="w-full text-xs text-neutral-400 hover:text-neutral-600 py-2">Batal</button>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ScannerFuturesPage() {
  const [agent1, setAgent1]           = useState<FuturesSignal[]>([]);
  const [agent2, setAgent2]           = useState<FuturesSignal[]>([]);
  const [agent3, setAgent3]           = useState<FuturesSignal[]>([]);
  const [loading, setLoading]         = useState(true);
  const [scanning, setScanning]       = useState(false);
  const [connState, setConnState]     = useState<ConnState>("connecting");
  const [isLive, setIsLive]           = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [scanned, setScanned]         = useState(0);
  const [activeAgent, setActiveAgent] = useState<"all" | "agent1" | "agent2" | "agent3">("all");
  const [dirFilter, setDirFilter]     = useState<"ALL" | "LONG" | "SHORT">("ALL");
  const [minScore, setMinScore]       = useState(52);
  const [search, setSearch]           = useState("");
  const [selected, setSelected]       = useState<FuturesSignal | null>(null);
  const [newSymbols, setNewSymbols]   = useState<Set<string>>(new Set());
  // Auto-trade
  const [autoEnabled, setAutoEnabled]       = useState(true);
  const [autoThreshold, setAutoThreshold]   = useState(72);   // UI-4: effective base threshold from API
  const [autoToggling, setAutoToggling]     = useState(false);
  // Open positions monitor
  const [openPositions, setOpenPositions]   = useState<OpenPosition[]>([]);

  const nextScanRef = useRef<number | null>(null);
  const [nextScanDisplay, setNextScanDisplay] = useState<number | null>(null);
  const prevSymsRef  = useRef<Set<string>>(new Set());

  // F99: pre-fill the symbol filter when arriving from the market overview (/scanner?symbol=BTC)
  useEffect(() => {
    const sym = new URLSearchParams(window.location.search).get("symbol");
    if (sym) setSearch(sym);
  }, []);

  // Fetch auto status + open positions on mount
  useEffect(() => {
    void (async () => {
      try {
        const [autoRes, riskRes] = await Promise.all([
          fetch("/api/v1/futures/auto/status"),
          fetch("/api/v1/futures/monitor/risk"),
        ]);
        if (autoRes.ok) {
          const a = await autoRes.json() as { enabled: boolean; threshold?: number };
          setAutoEnabled(a.enabled);
          if (typeof a.threshold === "number") setAutoThreshold(a.threshold);
        }
        if (riskRes.ok) {
          const r = await riskRes.json() as { positions: OpenPosition[] };
          setOpenPositions(r.positions ?? []);
        }
      } catch { /* silent */ }
    })();

    const t = setInterval(async () => {
      try {
        const r = await fetch("/api/v1/futures/monitor/risk");
        if (r.ok) {
          const d = await r.json() as { positions: OpenPosition[] };
          setOpenPositions(d.positions ?? []);
        }
      } catch { /* silent */ }
    }, 30_000);
    return () => clearInterval(t);
  }, []);

  const toggleAutoTrade = async () => {
    setAutoToggling(true);
    try {
      const res = await fetch("/api/v1/futures/auto/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !autoEnabled }),
      });
      if (res.ok) setAutoEnabled(v => !v);
    } catch { /* silent */ }
    finally { setAutoToggling(false); }
  };

  useEffect(() => {
    const t = setInterval(() => {
      if (nextScanRef.current != null && nextScanRef.current > 0) {
        nextScanRef.current--;
        setNextScanDisplay(nextScanRef.current);
      }
    }, 1000);
    return () => clearInterval(t);
  }, []);

  const applySnapshot = useCallback((data: Record<string, unknown>) => {
    const a1 = ((data.agent1 as Record<string, unknown> | undefined)?.results ?? []) as FuturesSignal[];
    const a2 = ((data.agent2 as Record<string, unknown> | undefined)?.results ?? []) as FuturesSignal[];
    const a3 = ((data.agent3 as Record<string, unknown> | undefined)?.results ?? []) as FuturesSignal[];
    const allSyms = new Set([...a1.map(r => r.symbol), ...a2.map(r => r.symbol), ...a3.map(r => r.symbol)]);
    const prev    = prevSymsRef.current;
    const fresh   = new Set<string>();
    if (prev.size > 0) allSyms.forEach(s => { if (!prev.has(s)) fresh.add(s); });
    prevSymsRef.current = allSyms;
    setAgent1(a1); setAgent2(a2); setAgent3(a3);
    setScanned(((data.agent1 as Record<string, unknown>)?.scanned as number) ?? 0);
    setLastUpdated(new Date()); setLoading(false); setScanning(false);
    if (typeof data.next_scan_in === "number") {
      nextScanRef.current = data.next_scan_in;
      setNextScanDisplay(data.next_scan_in);
    }
    if (fresh.size > 0) { setNewSymbols(fresh); setTimeout(() => setNewSymbols(new Set()), 8000); }
  }, []);

  useEffect(() => {
    if (!isLive) { setConnState("paused"); return; }
    let mounted = true, ws: WebSocket, timer: ReturnType<typeof setTimeout>;
    function connect() {
      if (!mounted) return;
      setConnState("connecting");
      ws = new WebSocket(futuresWsUrl());
      ws.onopen  = () => { if (mounted) setConnState("connected"); };
      ws.onmessage = (e) => {
        if (!mounted) return;
        try {
          const msg = JSON.parse(e.data as string) as Record<string, unknown>;
          if (msg.type === "snapshot")  applySnapshot(msg);
          if (msg.type === "scanning")  setScanning((msg.scanning as boolean) ?? true);
          if (msg.type === "heartbeat") {
            setScanning((msg.scanning as boolean) ?? false);
            if (typeof msg.next_scan_in === "number") { nextScanRef.current = msg.next_scan_in; setNextScanDisplay(msg.next_scan_in); }
          }
          if (msg.type === "status") setLoading(false);
        } catch { /* ignore */ }
      };
      ws.onclose = () => { if (!mounted) return; setConnState("reconnecting"); timer = setTimeout(connect, 3000); };
      ws.onerror = () => ws.close();
    }
    connect();
    return () => { mounted = false; clearTimeout(timer); ws?.close(); };
  }, [isLive, applySnapshot]);

  const manualScan = useCallback(async () => {
    setScanning(true);
    try {
      const r = await fetch("/api/v1/futures/scan", { method: "POST" });
      if (!r.ok) return;
      applySnapshot(await r.json() as Record<string, unknown>);
    } catch { /* silent */ } finally { setScanning(false); }
  }, [applySnapshot]);

  const filtered = useMemo(() => {
    const all: FuturesSignal[] =
      activeAgent === "agent1" ? agent1 :
      activeAgent === "agent2" ? agent2 :
      activeAgent === "agent3" ? agent3 :
      [...agent1, ...agent2, ...agent3];
    const q = search.trim().toLowerCase();
    return all.filter(s =>
      s.score >= minScore &&
      (dirFilter === "ALL" || s.direction === dirFilter) &&
      (!q || s.symbol.toLowerCase().includes(q))
    );
  }, [agent1, agent2, agent3, activeAgent, minScore, dirFilter, search]);

  const cm = CONN_META[connState];
  const scanProg = nextScanDisplay != null
    ? Math.round(((INTERVAL_SEC - nextScanDisplay) / INTERVAL_SEC) * 100) : 0;
  const fmtCD = (s: number | null) => s == null ? "--:--"
    : `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;
  // F40: dedupe by symbol across agents — one coin counted once per direction
  const allSignals = [...agent1, ...agent2, ...agent3];
  const totalLong  = new Set(allSignals.filter(s => s.direction === "LONG").map(s => s.symbol)).size;
  const totalShort = new Set(allSignals.filter(s => s.direction === "SHORT").map(s => s.symbol)).size;

  // Compute sets of open symbols for badge
  const openSymbolMap = useMemo(() => {
    const m: Record<string, OpenPosition> = {};
    openPositions.forEach(p => { m[`${p.symbol}-${p.agent}`] = p; });
    return m;
  }, [openPositions]);

  const atRiskCount = openPositions.filter(p => p.risk_status === "DANGER" || p.risk_status === "WARNING").length;

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white overflow-hidden">
        <div className="h-0.5 bg-neutral-700"><div className="h-full bg-teal-500 transition-all duration-1000" style={{ width: `${scanProg}%` }} /></div>
        <div className="p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <span className="text-3xl">⚡</span>
                <div>
                  <h1 className="text-2xl font-bold">Futures Scanner</h1>
                  <p className="text-xs text-neutral-400">Pre-Move (sebelum pump) · Momentum (saat bergerak) · New Listing · satu wallet cross-margin</p>
                </div>
              </div>
              <div className="flex gap-2 ml-12 flex-wrap">
                {[
                  { key: "agent1" as const, label: "🎯 Agent 1 — Pre-Gainer Scout",      cls: "bg-blue-500/20 border-blue-400/40 text-blue-300"     },
                  { key: "agent2" as const, label: "📦 Agent 2 — Accumulation Detector", cls: "bg-purple-500/20 border-purple-400/40 text-purple-300" },
                  { key: "agent3" as const, label: "🔥 Agent 3 — Momentum Capture",      cls: "bg-orange-500/20 border-orange-400/40 text-orange-300" },
                ].map(a => (
                  <button key={a.key}
                    onClick={() => setActiveAgent(prev => prev === a.key ? "all" : a.key)}
                    className={`text-[10px] font-bold px-3 py-1 rounded-full border transition-all ${activeAgent === a.key ? a.cls : "bg-white/5 border-white/10 text-neutral-400 hover:border-white/20"}`}>
                    {a.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-col items-end gap-3">
              <div className="flex items-center gap-2 flex-wrap justify-end">
                <button onClick={() => setIsLive(v => !v)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-bold border ${cm.color}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${cm.dot}`} />{cm.label}
                </button>
                {scanning && (
                  <span className="flex items-center gap-1.5 text-[11px] text-teal-300 bg-teal-500/10 border border-teal-500/30 px-3 py-1.5 rounded-full">
                    <span className="w-2 h-2 rounded-full bg-teal-400 animate-ping" />{scanned > 0 ? `Scanning ${scanned} pairs...` : "Scanning pairs..."}
                  </span>
                )}
                {!scanning && nextScanDisplay != null && connState === "connected" && (
                  <span className="text-[11px] text-neutral-400 font-mono">next <strong className="text-neutral-200">{fmtCD(nextScanDisplay)}</strong></span>
                )}
              </div>
              <div className="flex gap-2">
                {[
                  { label: "▲ LONG",  val: totalLong,  cls: "bg-green-500/15 border-green-500/25 text-green-400" },
                  { label: "▼ SHORT", val: totalShort, cls: "bg-red-500/15 border-red-500/25 text-red-400"       },
                  { label: "Pairs",   val: scanned,    cls: "bg-neutral-700/50 border-neutral-600/50 text-neutral-200" },
                ].map(s => (
                  <div key={s.label} className={`${s.cls} border rounded-xl px-3 py-2 text-center min-w-[55px]`}>
                    <p className="font-black text-2xl leading-tight">{s.val}</p>
                    <p className="text-[9px] opacity-80 mt-0.5">{s.label}</p>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2">
                {lastUpdated && <p className="text-[10px] text-neutral-400">{lastUpdated.toLocaleTimeString()}</p>}
                <button onClick={() => void manualScan()} disabled={scanning}
                  className="text-xs bg-teal-600 hover:bg-teal-500 disabled:opacity-40 px-3 py-1.5 rounded-lg font-semibold">
                  {scanning ? "Scanning..." : "⚡ Scan Sekarang"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Open Positions Monitor Panel ─────────────────────────────────────── */}
      {openPositions.length > 0 && (
        <div className={`rounded-2xl border p-4 ${atRiskCount > 0 ? "border-orange-300 bg-orange-50" : "border-neutral-200 bg-white"}`}>
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <p className={`text-xs font-bold uppercase tracking-wider ${atRiskCount > 0 ? "text-orange-700" : "text-neutral-600"}`}>
              {atRiskCount > 0 ? "⚠️" : "💼"} {openPositions.length} Posisi Terbuka
            </p>
            {atRiskCount > 0 && (
              <span className="text-[10px] text-red-600 bg-red-100 px-2 py-0.5 rounded-full font-bold border border-red-200">
                {atRiskCount} perlu perhatian!
              </span>
            )}
            <span className="ml-auto text-[10px] text-neutral-400">Detail di History → Monitor</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {openPositions.map(p => {
              const statusColor = p.risk_status === "DANGER" ? "border-red-300 bg-red-50 text-red-700" :
                                  p.risk_status === "WARNING" ? "border-yellow-300 bg-yellow-50 text-yellow-700" :
                                  p.upnl_pct > 0 ? "border-green-200 bg-green-50 text-green-700" :
                                  "border-neutral-200 bg-neutral-50 text-neutral-600";
              return (
                <div key={p.id} className={`flex items-center gap-2 text-xs font-semibold px-3 py-2 rounded-xl border ${statusColor}`}>
                  <span>{p.symbol.replace("USDT", "")}</span>
                  <span className="text-[9px] opacity-70">{p.direction === "LONG" ? "▲" : "▼"} {p.leverage}x</span>
                  <span className="font-black">{p.upnl_pct >= 0 ? "+" : ""}{p.upnl_pct.toFixed(2)}%</span>
                  {p.auto_opened && <span className="text-[8px] bg-teal-200 text-teal-800 px-1 rounded font-bold">AUTO</span>}
                  {p.risk_status !== "SAFE" && (
                    <span className="text-[8px]">{p.risk_status === "DANGER" ? "🚨" : "⚠️"} Liq {p.liq_dist_pct.toFixed(1)}%</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Auto-trade + Filters ────────────────────────────────────────────────── */}
      {/* Auto-trade toggle */}
      <div className={`flex items-center gap-3 px-4 py-3 rounded-2xl border ${autoEnabled ? "bg-teal-50 border-teal-200" : "bg-neutral-50 border-neutral-200"}`}>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-neutral-700">⚡ Auto-Open Posisi</span>
            {autoEnabled && (
              <span className="text-[10px] bg-teal-600 text-white px-2 py-0.5 rounded-full font-bold">AKTIF</span>
            )}
          </div>
          <p className="text-[11px] text-neutral-500 mt-0.5">
            Score ≥ {autoThreshold}pt → otomatis buka paper trade · Max 6 posisi (global, 1 wallet) · dedup per koin
          </p>
        </div>
        <button
          onClick={() => void toggleAutoTrade()}
          disabled={autoToggling}
          className={`shrink-0 w-12 h-6 rounded-full transition-all relative ${autoEnabled ? "bg-teal-500" : "bg-neutral-300"} disabled:opacity-50`}
        >
          <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-all ${autoEnabled ? "left-6" : "left-0.5"}`} />
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        {(["ALL", "LONG", "SHORT"] as const).map(d => (
          <button key={d} onClick={() => setDirFilter(d)}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-all ${
              dirFilter === d
                ? d === "LONG" ? "bg-green-600 text-white" : d === "SHORT" ? "bg-red-600 text-white" : "bg-neutral-900 text-white"
                : "bg-white border border-neutral-200 text-neutral-600 hover:border-neutral-400"
            }`}>
            {d === "LONG" ? "▲ LONG" : d === "SHORT" ? "▼ SHORT" : "Semua"}
          </button>
        ))}
        <div className="flex items-center gap-1.5 bg-white border border-neutral-200 rounded-full px-3 py-1.5">
          <span className="text-neutral-400 text-[10px] font-semibold">MIN</span>
          <select value={minScore} onChange={e => setMinScore(Number(e.target.value))}
            className="text-xs text-neutral-700 bg-transparent focus:outline-none">
            <option value={52}>52pt</option>
            <option value={60}>60pt ⚡</option>
            <option value={72}>72pt 🔥 Auto</option>
            <option value={80}>80pt 💎</option>
          </select>
        </div>
        <div className="relative flex-1 min-w-[140px] max-w-[200px]">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400 text-xs">🔍</span>
          <input type="text" placeholder="Cari koin..." value={search} onChange={e => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-white border border-neutral-200 rounded-full text-xs focus:outline-none focus:border-teal-400" />
        </div>
        {newSymbols.size > 0 && (
          <span className="flex items-center gap-1.5 text-xs text-teal-600 font-semibold animate-pulse">
            <span className="w-2 h-2 rounded-full bg-teal-400" />{newSymbols.size} sinyal baru
          </span>
        )}
        <span className="text-xs text-neutral-400 ml-auto">{filtered.length} sinyal</span>
      </div>

      {/* Loading */}
      {loading && !agent1.length && !agent2.length && !agent3.length && (
        <div className="py-20 text-center space-y-3">
          <div className="w-14 h-14 rounded-full bg-teal-100 flex items-center justify-center mx-auto">
            <span className="text-3xl animate-bounce">⚡</span>
          </div>
          <p className="font-semibold text-neutral-700">Menghubungkan ke Pre-Gainer Scanner...</p>
          <p className="text-xs text-neutral-400">Pre-Gainer + Accumulation + Momentum · 150 USDT-M pairs + new listings</p>
        </div>
      )}

      {/* Market Intel Banner */}
      <MarketIntelBanner mode="futures" />

      {/* Cards */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {filtered.map(s => {
            const opKey = `${s.symbol}-${s.agent}`;
            const op = openSymbolMap[opKey];
            return (
              <SignalCard
                key={`${s.agent}-${s.symbol}`}
                s={s}
                isNew={newSymbols.has(s.symbol)}
                isOpen={!!op}
                openPos={op}
                onClick={() => setSelected(s)}
                autoThreshold={autoThreshold}
              />
            );
          })}
        </div>
      )}

      {/* Empty */}
      {!loading && filtered.length === 0 && (agent1.length > 0 || agent2.length > 0 || agent3.length > 0) && (
        <div className="text-center py-12 text-neutral-400">
          <p className="text-3xl mb-3">🔍</p>
          <p className="font-semibold">Tidak ada sinyal untuk filter ini</p>
          <button onClick={() => { setDirFilter("ALL"); setMinScore(52); setSearch(""); setActiveAgent("all"); }}
            className="mt-3 text-sm text-teal-600 underline">Reset filter</button>
        </div>
      )}
      {!loading && !scanning && !agent1.length && !agent2.length && !agent3.length && (
        <div className="space-y-4">
          <div className="text-center py-8 text-neutral-400">
            <p className="text-3xl mb-3">📡</p>
            <p className="font-semibold">Belum ada data</p>
            <p className="text-xs mt-1">Klik ⚡ Scan Sekarang untuk mulai</p>
          </div>
        </div>
      )}
      {/* Modal */}
      {selected && <TradeModal s={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
