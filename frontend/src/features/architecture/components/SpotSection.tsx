"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, SectionTitle } from "./primitives";
import {
  SPOT_LANES,
  SPOT_SIGNALS,
  SPOT_DIRECTION_GATE,
  SPOT_MONITOR_LAYERS,
  SYSTEM_OVERVIEW,
} from "../data";

// ─── UNIVERSE OVERVIEW ────────────────────────────────────────────────────────
function UniverseBar() {
  const o = SYSTEM_OVERVIEW.spot;
  const stats = [
    { label: "Scan Interval",     val: o.scanInterval },
    { label: "Monitor",           val: o.monitorInterval },
    { label: "Fastpass BigMover", val: o.fastpassInterval.replace(" (BigMover)", "") },
    { label: "Min Volume",        val: o.minVolume },
    { label: "Min Score",         val: String(o.minScore) },
    { label: "Auto-Open",         val: String(o.autoOpenScore) },
    { label: "R:R Min",           val: `≥ ${o.rrMin}` },
    { label: "Max Open/Cycle",    val: String(o.maxOpensCycle) },
  ];
  return (
    <div className="grid grid-cols-4 md:grid-cols-8 gap-2 mb-6">
      {stats.map(s => (
        <div key={s.label} className="bg-neutral-50 border rounded-xl px-3 py-2 text-center">
          <p className="text-[10px] text-neutral-500 font-medium">{s.label}</p>
          <p className="text-xs font-bold text-teal-700 mt-0.5">{s.val}</p>
        </div>
      ))}
    </div>
  );
}

// ─── 4 LANES ─────────────────────────────────────────────────────────────────
function LanesSection() {
  const [active, setActive] = useState(SPOT_LANES[0].key);
  const lane = SPOT_LANES.find(l => l.key === active)!;

  return (
    <div className="mb-6">
      <SectionTitle icon="🛣" title="4 Scanning Lanes" sub="Setiap lane punya universe, trigger, dan SL/TP berbeda" />
      <div className="flex gap-2 mb-4 flex-wrap">
        {SPOT_LANES.map(l => (
          <button key={l.key} onClick={() => setActive(l.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-bold transition-all ${
              active === l.key
                ? "bg-teal-600 text-white border-teal-600"
                : "bg-white border-neutral-200 text-neutral-600 hover:border-teal-300"
            }`}>
            <span>{l.emoji}</span> {l.label}
          </button>
        ))}
      </div>

      <div className={`rounded-xl border p-4 ${lane.color}`}>
        <div className="flex items-start justify-between gap-4 mb-3">
          <div>
            <p className="text-base font-bold flex items-center gap-2">{lane.emoji} {lane.label}</p>
            <p className="text-xs mt-1 opacity-80 max-w-xl">{lane.desc}</p>
          </div>
          <div className="text-right shrink-0 space-y-1">
            <Badge label={`Min Score: ${lane.minScore}`} color={lane.badgeColor} />
            <div />
            <Badge label={`Auto-Open: ${lane.autoScore}`} color={lane.badgeColor} />
          </div>
        </div>

        <div className="grid md:grid-cols-2 gap-3">
          <div className="space-y-2">
            <InfoRow label="Trigger" val={lane.trigger} />
            <InfoRow label="SL Method" val={lane.slMethod} />
            <InfoRow label="SL Range" val={lane.slRange} />
            <InfoRow label="R:R Min" val={`≥ ${lane.rrMin}`} />
            <InfoRow label="Max Age" val={lane.maxAge} />
            {lane.tp1Partial && <InfoRow label="TP1 Action" val={lane.tp1Partial} />}
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider opacity-60 mb-2">Take Profit Levels</p>
            {lane.tp.map((t, i) => (
              <div key={i} className="flex items-start gap-2 mb-1.5">
                <span className="shrink-0 w-6 h-6 rounded-full bg-white/60 flex items-center justify-center text-[10px] font-bold">{i + 1}</span>
                <p className="text-xs leading-relaxed">{t}</p>
              </div>
            ))}
            {lane.extras && (
              <div className="mt-3 pt-3 border-t border-current/10 space-y-1">
                {lane.extras.map(e => (
                  <p key={e} className="text-[11px] opacity-70 flex items-start gap-1">
                    <span className="text-teal-600 shrink-0">›</span> {e}
                  </p>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, val }: { label: string; val: string }) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="shrink-0 font-semibold opacity-60 w-24">{label}</span>
      <span className="font-medium">{val}</span>
    </div>
  );
}

// ─── 12 SIGNALS ───────────────────────────────────────────────────────────────
function SignalsSection() {
  const [active, setActive] = useState(SPOT_SIGNALS[0].id);
  const sig = SPOT_SIGNALS.find(s => s.id === active)!;

  const catColor: Record<string, string> = {
    setup:    "bg-blue-100 text-blue-700",
    timing:   "bg-orange-100 text-orange-700",
    market:   "bg-purple-100 text-purple-700",
    momentum: "bg-amber-100 text-amber-700",
    trend:    "bg-teal-100 text-teal-700",
  };

  return (
    <div className="mb-6">
      <SectionTitle icon="🔭" title="12 Scoring Signals" sub="Akumulasi poin dari 12 sinyal — threshold 65 untuk open, 85 untuk auto-open" />

      {/* Direction Gate note */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 mb-4">
        <p className="text-xs font-bold text-amber-800 mb-1">⚡ Direction Gate — wajib untuk auto-open & BB Squeeze full points</p>
        <p className="text-[11px] text-amber-700">
          {SPOT_DIRECTION_GATE.conditions.join(" ")}
        </p>
      </div>

      {/* Signal selector */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-1.5 mb-4">
        {SPOT_SIGNALS.map(s => (
          <button key={s.id} onClick={() => setActive(s.id)}
            className={`flex flex-col items-center gap-0.5 px-2 py-2 rounded-lg border text-center transition-all ${
              active === s.id
                ? "bg-teal-600 text-white border-teal-600"
                : "bg-white border-neutral-200 text-neutral-600 hover:border-teal-300"
            }`}>
            <span className="text-base">{s.emoji}</span>
            <span className="text-[9px] font-bold leading-tight">{s.name.split(" ").slice(0, 2).join(" ")}</span>
            <span className={`text-[9px] px-1 rounded-full font-bold ${active === s.id ? "bg-white/20 text-white" : "bg-teal-50 text-teal-700"}`}>
              +{s.maxPts}
            </span>
          </button>
        ))}
      </div>

      {/* Signal detail */}
      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-2xl">{sig.emoji}</span>
            <div>
              <p className="font-bold text-neutral-800">{sig.name}</p>
              <div className="flex gap-1 mt-0.5">
                <Badge label={`Max ${sig.maxPts} pts`} color="bg-teal-100 text-teal-700" />
                <Badge label={sig.category} color={catColor[sig.category] ?? "bg-neutral-100 text-neutral-600"} />
              </div>
            </div>
          </div>
          <pre className="bg-neutral-900 text-green-400 text-[10px] font-mono p-3 rounded-lg overflow-x-auto leading-relaxed whitespace-pre-wrap mb-3">
            {sig.formula}
          </pre>
        </div>
        <div className="space-y-3">
          <div>
            <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wide mb-2">Scoring</p>
            <div className="space-y-1.5">
              {sig.scoring.map((sc, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="shrink-0 w-10 font-black text-teal-600 text-right">+{sc.pts}</span>
                  <span className="text-neutral-700">{sc.cond}</span>
                  {sc.note && <Badge label={sc.note} color="bg-blue-50 text-blue-600" />}
                </div>
              ))}
              {sig.penalties?.map((p, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="shrink-0 w-10 font-black text-red-500 text-right">{p.pts}</span>
                  <span className="text-neutral-700">{p.cond}</span>
                  {p.note && <Badge label={p.note} color="bg-red-50 text-red-600" />}
                </div>
              ))}
            </div>
          </div>
          <div className="bg-neutral-50 rounded-xl p-3 border">
            <p className="text-[10px] font-bold text-neutral-500 mb-1">💡 Kenapa works?</p>
            <p className="text-[11px] text-neutral-700 leading-relaxed">{sig.why}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── MONITOR LAYERS ───────────────────────────────────────────────────────────
function MonitorSection() {
  const [open, setOpen] = useState<string | null>("L1");
  return (
    <div>
      <SectionTitle icon="👁" title="Monitor — 5 Exit Layers" sub="Berjalan setiap 60s (+ wick detection 1m). Layer diproses berurutan L0 → L4." />
      <div className="space-y-2">
        {SPOT_MONITOR_LAYERS.map(layer => (
          <div key={layer.layer} className={`rounded-xl border overflow-hidden ${layer.color}`}>
            <button className="w-full flex items-center gap-3 px-4 py-3 text-left" onClick={() => setOpen(open === layer.layer ? null : layer.layer)}>
              <span className="text-base w-7 shrink-0">{layer.emoji}</span>
              <div className="flex-1">
                <p className="text-xs font-bold text-neutral-800">{layer.layer} — {layer.title}</p>
                <p className="text-[11px] text-neutral-500 mt-0.5">{layer.desc}</p>
              </div>
              <span className="text-neutral-400 text-sm">{open === layer.layer ? "▲" : "▼"}</span>
            </button>
            {open === layer.layer && (
              <div className="px-4 pb-4 pt-0 border-t border-neutral-200">
                <div className="space-y-2 mt-3">
                  {layer.closes.map((c, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <span className="shrink-0 w-2 h-2 rounded-full bg-neutral-400 mt-1.5" />
                      <div>
                        <p className="text-xs text-neutral-700">{c.reason}</p>
                        {c.note && <p className="text-[10px] text-neutral-500 mt-0.5">→ {c.note}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────
export function SpotSection() {
  return (
    <div className="space-y-2">
      <Card><CardContent className="pt-5"><UniverseBar /><LanesSection /></CardContent></Card>
      <Card><CardContent className="pt-5"><SignalsSection /></CardContent></Card>
      <Card><CardContent className="pt-5"><MonitorSection /></CardContent></Card>
    </div>
  );
}
