"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, LiveBadge, SectionTitle, SourceBadge } from "./primitives";
import {
  FUTURES_AGENTS,
  FUTURES_MONITOR_LAYERS,
  LEVERAGE_CALC,
  RISK_GATE,
  SYSTEM_OVERVIEW,
} from "../data";
import { useAgentConfig } from "../hooks/useAgentConfig";
import { useAgentConfigDbKeys } from "../hooks/useAgentConfigDbKeys";

// data.ts lane key ("agent1") → live API agent key ("pre_gainer")
const LIVE_AGENT_KEY: Record<string, string> = {
  agent1: "pre_gainer",
  agent2: "accumulation",
  agent3: "momentum",
  bigmover: "bigmover",
};

// ─── SYSTEM STATS ─────────────────────────────────────────────────────────────
function FuturesStatsBar() {
  const { data, loading } = useAgentConfig();
  const dbKeys = useAgentConfigDbKeys();
  const live = data?.futures;
  const o = SYSTEM_OVERVIEW.futures;

  const stats: { label: string; val: string; dbKey?: string }[] = [
    { label: "Scan Interval",   val: live?.scan_interval_sec != null ? `${Math.round(live.scan_interval_sec / 60)} menit` : o.scanInterval },
    { label: "Monitor",         val: live?.monitor_interval_sec != null ? `${Math.round(live.monitor_interval_sec / 60)} menit` : o.monitorInterval },
    { label: "Fast Monitor",    val: o.fastMonitorInterval.replace(" (high-risk)", "") },
    { label: "Max Positions",   val: live ? `${live.auto_trader?.max_positions_global} global` : `${o.maxPositions} global`, dbKey: "futures.max_auto_positions" },
    { label: "Min Score",       val: String(o.minScore) },
    { label: "Auto-Open",       val: o.autoOpenScore },
    { label: "Max Age",         val: live ? `${live.monitor?.max_age_days}–${(live.monitor?.max_age_days ?? 0) + (live.monitor?.max_age_extensions ?? 0)} hari` : o.maxAge },
    { label: "Circuit Breaker", val: live ? `−${live.risk_gate?.dd_hard_stop_pct}%` : `−${o.circuitBreakerPct}%` },
  ];
  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-400">System Overview</p>
        <LiveBadge live={!!live} loading={loading} />
      </div>
      <div className="grid grid-cols-4 md:grid-cols-8 gap-2">
        {stats.map(s => (
          <div key={s.label} className="bg-neutral-50 border rounded-xl px-3 py-2 text-center">
            <p className="text-[10px] text-neutral-500 font-medium flex items-center justify-center">
              {s.label}
              {s.dbKey && <SourceBadge dbKey={s.dbKey} dbKeys={dbKeys} />}
            </p>
            <p className="text-xs font-bold text-blue-700 mt-0.5">{s.val}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 4 AGENTS ────────────────────────────────────────────────────────────────
function AgentsSection() {
  const [active, setActive] = useState(FUTURES_AGENTS[0].key);
  const agent = FUTURES_AGENTS.find(a => a.key === active)!;
  const { data } = useAgentConfig();
  const dbKeys = useAgentConfigDbKeys();
  const liveAgent = data?.futures?.agents?.[LIVE_AGENT_KEY[active] ?? active];
  const minScore = (liveAgent?.min_score as number | undefined) ?? agent.minScore;
  // Only bigmover's min_score is DB-wired (fixed threshold) — agent1/2/3 use
  // adaptive thresholds from weight_updater, which aren't a static agent_config row.
  const minScoreDbKey = active === "bigmover" ? "futures.bigmover_min_score" : undefined;

  return (
    <div className="mb-6">
      <SectionTitle icon="🤖" title="4 Futures Agents" sub="Setiap agent punya filosofi, scoring, dan risk budget berbeda" />

      <div className="flex gap-2 mb-4 flex-wrap">
        {FUTURES_AGENTS.map(a => (
          <button key={a.key} onClick={() => setActive(a.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-bold transition-all ${
              active === a.key
                ? "bg-blue-600 text-white border-blue-600"
                : "bg-white border-neutral-200 text-neutral-600 hover:border-blue-300"
            }`}>
            {a.emoji} {a.label}
          </button>
        ))}
      </div>

      <div className={`rounded-xl border p-4 bg-gradient-to-br ${agent.color}`}>
        {/* Header */}
        <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
          <div>
            <p className="text-lg font-bold flex items-center gap-2">{agent.emoji} {agent.label}</p>
            <p className="text-xs text-neutral-600 mt-1 max-w-lg">{agent.philosophy}</p>
            <div className="flex gap-1.5 mt-2">
              <Badge label={`Max ${agent.leverageMax}×`} color={agent.badgeColor} />
              <Badge label={agent.direction} color="bg-neutral-100 text-neutral-700" />
              <Badge label={`Min ${minScore} pts`} color={agent.badgeColor} />
              {minScoreDbKey && <SourceBadge dbKey={minScoreDbKey} dbKeys={dbKeys} />}
            </div>
          </div>
          <div className="text-xs text-neutral-600 bg-white/60 rounded-xl p-3 space-y-1 shrink-0">
            <p><span className="font-semibold">SL Method:</span> {agent.slMethod}</p>
            <p><span className="font-semibold">SL Cap:</span> {agent.slCap}</p>
            <p><span className="font-semibold">Max Margin Loss:</span> {agent.maxMarginLoss}</p>
            <p className="text-[10px] text-neutral-400 font-mono">{agent.file}</p>
          </div>
        </div>

        {/* Signals grid */}
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Scoring Signals</p>
          <div className="grid md:grid-cols-2 gap-2">
            {agent.signals.map((s, i) => (
              <div key={i} className="bg-white/70 rounded-lg p-2.5">
                <div className="flex items-center justify-between mb-1">
                  <p className="text-xs font-bold text-neutral-800">{s.name}</p>
                  <Badge label={`+${s.maxPts}`} color="bg-teal-50 text-teal-700" />
                </div>
                <p className="text-[10px] text-neutral-500 leading-relaxed whitespace-pre-line">{s.detail}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Penalties */}
        {agent.penalties.length > 0 && (
          <div className="mt-3 pt-3 border-t border-neutral-200">
            <p className="text-[10px] font-bold uppercase tracking-wider text-red-600 mb-2">Penalties & Skip Conditions</p>
            <div className="space-y-1">
              {agent.penalties.map((p, i) => (
                <p key={i} className="text-xs text-red-700 flex items-start gap-1.5">
                  <span className="shrink-0 text-red-400">⚠</span> {p}
                </p>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── LEVERAGE CALC ────────────────────────────────────────────────────────────
function LeverageSection() {
  return (
    <div className="mb-6">
      <SectionTitle icon="📐" title="Leverage Calculation" sub="Base dari ATR volatilitas, lalu score bonus, lalu di-cap per lane" />
      <div className="grid md:grid-cols-3 gap-4">
        {/* Base */}
        <div className="bg-neutral-50 border rounded-xl p-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Base Leverage (dari ATR 15m)</p>
          <div className="space-y-1.5">
            {LEVERAGE_CALC.base.map((r, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="text-neutral-600">ATR {r.atr}</span>
                <Badge label={`${r.base}×`} color="bg-blue-50 text-blue-700" />
              </div>
            ))}
          </div>
          <div className="mt-3 pt-2 border-t space-y-1">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-1">Score Bonus</p>
            {LEVERAGE_CALC.scoreBonus.map((b, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="text-neutral-600">Score {b.score}</span>
                <span className="font-bold text-teal-600">{b.bonus}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Lane Caps */}
        <div className="bg-neutral-50 border rounded-xl p-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Lane Caps</p>
          <div className="space-y-2">
            {LEVERAGE_CALC.laneCaps.map((l, i) => (
              <div key={i} className="flex items-start justify-between text-xs gap-2">
                <span className="text-neutral-600 font-mono">{l.lane}</span>
                <div className="text-right">
                  <p className="font-bold text-blue-700">{l.maxLev}× max</p>
                  <p className="text-[10px] text-neutral-500">SL Margin {l.slMargin}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Liq Guard */}
        <div className="bg-neutral-50 border rounded-xl p-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Liquidation Guard</p>
          <p className="text-[11px] text-neutral-500 mb-2">Tutup posisi darurat jika harga mendekati likuidasi</p>
          <div className="space-y-1.5">
            {LEVERAGE_CALC.liqGuard.map((g, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="text-neutral-600">{g.leverage}</span>
                <Badge label={`≤ ${g.guardPct}`} color="bg-red-50 text-red-700" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── MONITOR WATERFALL ────────────────────────────────────────────────────────
function MonitorSection() {
  const [open, setOpen] = useState<string | null>("TP1 Partial");
  return (
    <div className="mb-6">
      <SectionTitle icon="👁" title="Futures Monitor — Exit Waterfall" sub="Proses trail SL, TP extensions, emergency exits. Berjalan setiap 2 menit." />
      <div className="space-y-2">
        {FUTURES_MONITOR_LAYERS.map(layer => (
          <div key={layer.label} className={`rounded-xl border overflow-hidden ${layer.color}`}>
            <button className="w-full flex items-center gap-3 px-4 py-3 text-left" onClick={() => setOpen(open === layer.label ? null : layer.label)}>
              <span className="text-base w-7 shrink-0">{layer.emoji}</span>
              <p className="text-xs font-bold text-neutral-800 flex-1">{layer.label}</p>
              <span className="text-neutral-400 text-sm">{open === layer.label ? "▲" : "▼"}</span>
            </button>
            {open === layer.label && (
              <div className="px-4 pb-4 border-t border-neutral-200">
                <pre className="mt-3 text-[11px] text-neutral-700 leading-relaxed whitespace-pre-wrap font-sans">
                  {layer.detail}
                </pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── RISK GATE ────────────────────────────────────────────────────────────────
function RiskGateSection() {
  return (
    <div>
      <SectionTitle icon="🛡" title="Risk Gate — Circuit Breaker" sub="3 mekanisme cegah death spiral: drawdown gate, RAR gate, per-lane WR pause" />
      <div className="grid md:grid-cols-3 gap-4">
        {/* Gate States */}
        <div className="space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Gate States</p>
          {RISK_GATE.states.map(s => (
            <div key={s.state} className={`rounded-xl border p-3 ${s.color}`}>
              <p className="text-xs font-bold">{s.state}</p>
              <p className="text-[11px] mt-0.5 opacity-80">{s.desc}</p>
            </div>
          ))}
        </div>

        {/* Drawdown Thresholds */}
        <div className="bg-neutral-50 border rounded-xl p-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Drawdown Thresholds (wallet size)</p>
          <div className="space-y-2">
            {RISK_GATE.drawdownThresholds.map((d, i) => (
              <div key={i} className="flex items-center justify-between text-xs gap-2 border-b border-neutral-100 pb-1 last:border-0">
                <span className="text-neutral-600 font-mono">{d.wallet}</span>
                <div className="text-right">
                  <p className="font-bold text-red-600">Stop: −{d.hardStop}</p>
                  <p className="text-[10px] text-green-600">Resume: −{d.recover}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* RAR Gate + Lane WR */}
        <div className="space-y-3">
          <div className="bg-purple-50 border border-purple-200 rounded-xl p-3">
            <p className="text-xs font-bold text-purple-800 mb-1">RAR Gate (Sharpe Proxy)</p>
            <p className="text-[11px] text-purple-700 font-mono mb-1">{RISK_GATE.rarGate.formula}</p>
            <p className="text-[11px] text-purple-700">Trigger: {RISK_GATE.rarGate.trigger}</p>
          </div>
          <div className="bg-orange-50 border border-orange-200 rounded-xl p-3">
            <p className="text-xs font-bold text-orange-800 mb-1">Per-Lane WR Auto-Pause</p>
            <p className="text-[11px] text-orange-700 mb-1">
              Rolling {RISK_GATE.laneWRPause.rolling} trade · threshold {RISK_GATE.laneWRPause.threshold}
            </p>
            <p className="text-[11px] text-orange-700">Pause: {RISK_GATE.laneWRPause.duration}</p>
            <p className="text-[10px] text-orange-600 mt-1">{RISK_GATE.laneWRPause.desc}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────
export function FuturesSection() {
  return (
    <div className="space-y-2">
      <Card><CardContent className="pt-5"><FuturesStatsBar /><AgentsSection /><LeverageSection /></CardContent></Card>
      <Card><CardContent className="pt-5"><MonitorSection /></CardContent></Card>
      <Card><CardContent className="pt-5"><RiskGateSection /></CardContent></Card>
    </div>
  );
}
