"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { SpotSection } from "./components/SpotSection";
import { FuturesSection } from "./components/FuturesSection";
import { LearningSection } from "./components/LearningSection";

const TOP_TABS = [
  { key: "spot",    label: "🎯 SPOT",      sub: "4 Lanes · 12 Signals · 5 Exit Layers" },
  { key: "futures", label: "⚡ FUTURES",   sub: "4 Agents · Leverage · Monitor · Risk Gate" },
  { key: "learning",label: "🧠 Learning",  sub: "Adaptive Weights · Auto-Threshold · Blacklist · Tech" },
] as const;

type TabKey = (typeof TOP_TABS)[number]["key"];

export default function ArchitecturePage() {
  const [tab, setTab] = useState<TabKey>("spot");

  return (
    <div className="space-y-4 max-w-5xl mx-auto">

      {/* Hero */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6 pb-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-2xl font-bold mb-1">📐 Arsitektur Sistem</h1>
              <p className="text-sm text-neutral-400 max-w-2xl leading-relaxed">
                Crypto trading agent dengan{" "}
                <strong className="text-teal-400">Spot Opportunity</strong>{" "}
                (4 lanes, 12 sinyal, adaptive scoring) dan{" "}
                <strong className="text-blue-400">Futures</strong>{" "}
                (4 agents, ATR leverage, risk gate, circuit breaker).
                Total <strong className="text-white">7 autonomous agents</strong> + adaptive signal weighting.
              </p>
            </div>
            <div className="flex gap-3 flex-wrap">
              {[
                { n: "7", lbl: "Agents" },
                { n: "12", lbl: "SPOT Signals" },
                { n: "4+4", lbl: "Lanes/Agents" },
                { n: "≥3.5×", lbl: "R:R SPOT" },
              ].map(s => (
                <div key={s.lbl} className="text-center bg-white/5 border border-white/10 rounded-xl px-4 py-2">
                  <p className="text-xl font-black text-teal-400">{s.n}</p>
                  <p className="text-[10px] text-neutral-400">{s.lbl}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Agent status pills */}
          <div className="flex gap-2 mt-4 flex-wrap">
            {[
              { icon: "🎯", label: "Spot Scanner",    sub: "3 min cycle",    color: "bg-teal-500/20 border-teal-400/30"    },
              { icon: "📍", label: "Spot Monitor",    sub: "60s · L0–L4",   color: "bg-amber-500/20 border-amber-400/30"  },
              { icon: "⚡", label: "Pre-Gainer",      sub: "Futures · 5min", color: "bg-blue-500/20 border-blue-400/30"    },
              { icon: "📦", label: "Accumulation",    sub: "Futures · T0-T4",color: "bg-purple-500/20 border-purple-400/30"},
              { icon: "🔥", label: "Momentum",        sub: "Futures · 5min", color: "bg-orange-500/20 border-orange-400/30"},
              { icon: "💥", label: "Big Mover",       sub: "Futures · 5min", color: "bg-yellow-500/20 border-yellow-400/30"},
              { icon: "🧠", label: "Weight Updater",  sub: "Learning · 6h",  color: "bg-green-500/20 border-green-400/30"  },
            ].map(a => (
              <div key={a.label} className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border ${a.color}`}>
                <span className="text-sm">{a.icon}</span>
                <div>
                  <p className="text-[11px] font-bold text-white">{a.label}</p>
                  <p className="text-[9px] text-neutral-400">{a.sub}</p>
                </div>
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse ml-1" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Top-level tab switcher */}
      <div className="flex bg-neutral-100 rounded-xl p-1 gap-1">
        {TOP_TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex-1 flex flex-col items-center py-2.5 px-3 rounded-lg transition-all ${
              tab === t.key
                ? "bg-white shadow text-neutral-900"
                : "text-neutral-500 hover:text-neutral-700"
            }`}>
            <span className="text-sm font-bold">{t.label}</span>
            <span className="text-[10px] text-neutral-400 mt-0.5 hidden sm:block">{t.sub}</span>
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "spot"     && <SpotSection />}
      {tab === "futures"  && <FuturesSection />}
      {tab === "learning" && <LearningSection />}

    </div>
  );
}
