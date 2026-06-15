"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { BUGS_FIXED, NEW_FEATURES, TA_SIGNALS, STYLES } from "./data";
import { AgentsCard } from "./components/AgentsCard";
import { DataFlowCard } from "./components/DataFlowCard";
import { SpotLifecycleCard } from "./components/SpotLifecycleCard";
import { Code, Badge, SectionTitle, Tabs } from "./components/primitives";

const AGENT_PILLS = [
  { icon: "⚡", label: "Futures Scanner",  sub: "1 agent · Pre-Move/Momentum/New", color: "bg-blue-500/20 border-blue-400/30"    },
  { icon: "👁", label: "Futures Monitor",  sub: "1 agent · TP/SL/wick · 120s",     color: "bg-indigo-500/20 border-indigo-400/30" },
  { icon: "🧠", label: "Weight Updater",   sub: "Learning · 6jam",                 color: "bg-green-500/20 border-green-400/30"   },
  { icon: "🚀", label: "Spot Opp Scanner", sub: "Spot · 15m",                      color: "bg-teal-500/20 border-teal-400/30"     },
  { icon: "📍", label: "Spot Monitor",     sub: "Spot · TP/SL · 60s",              color: "bg-amber-500/20 border-amber-400/30"   },
];

const SCORE_RANGES = [
  { range: "≥ 70",  label: "Setup Sangat Kuat", desc: "Multiple signal confirm", cls: "bg-green-50 border-green-200 text-green-700"     },
  { range: "50–69", label: "Setup Bagus",       desc: "Monitor lebih lanjut",    cls: "bg-yellow-50 border-yellow-200 text-yellow-700"  },
  { range: "30–49", label: "Early Stage",       desc: "Belum cukup konfirmasi",  cls: "bg-neutral-50 border-neutral-200 text-neutral-500" },
];

const REGIMES = [
  { regime: "trending_up",   threshold: "≥ 72",          action: "✅ Buka LONG priority",              cls: "bg-green-50 border-green-200"         },
  { regime: "trending_down", threshold: "≥ 72",          action: "✅ Buka SHORT priority",             cls: "bg-red-50 border-red-200"             },
  { regime: "ranging",       threshold: "≥ 77",          action: "⚠️ Buka tapi threshold +5",          cls: "bg-yellow-50 border-yellow-200"       },
  { regime: "volatile",      threshold: "Momentum saja", action: "🔥 Pre-Move diblokir, Momentum jalan", cls: "bg-orange-50 border-orange-300 font-bold" },
];

const TECH_STACK = [
  { layer: "Backend",         items: ["FastAPI + Python 3.12", "SQLAlchemy async", "asyncpg / PostgreSQL 16", "Redis 7 (cache & pub/sub)", "HTTPX (Binance REST)", "Structlog"] },
  { layer: "TA Engine (T0-T4)", items: ["T0: Wyckoff phase detection", "T1: EMA/ADX trend analysis", "T2: S/R swing pivot zones", "T3: BB/Vol/RSI/candle patterns", "T4: Trigger confirmation", "ATR + Fibonacci fallback"] },
  { layer: "Frontend",        items: ["Next.js 16 (App Router)", "TypeScript + Tailwind v4", "Recharts (equity curve)", "WebSocket live updates", "System Health monitoring", "Browser Notification API"] },
  { layer: "Agents & Infra",  items: ["6 asyncio background agents", "Binance Spot + Futures REST", "Order book depth (Spot)", "Adaptive signal weighting", "Docker Compose (local)", "PostgreSQL 16 + Redis 7"] },
];

export default function ArchitecturePage() {
  const [taTab,    setTaTab]    = useState("BB Squeeze");
  const [styleTab, setStyleTab] = useState("Scalping");
  const [agentTab, setAgentTab] = useState("Pre-Gainer");
  const [bugTab,   setBugTab]   = useState("Fixed");

  const activeSig   = TA_SIGNALS[taTab    as keyof typeof TA_SIGNALS];
  const activeStyle = STYLES[styleTab     as keyof typeof STYLES];

  return (
    <div className="space-y-6 max-w-5xl mx-auto">

      {/* Hero */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6 pb-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-3xl font-bold mb-1">📐 Arsitektur Sistem</h1>
              <p className="text-sm text-neutral-400 max-w-2xl leading-relaxed">
                Crypto trading agent dengan <strong className="text-white">2 sistem independen</strong>:{" "}
                <strong className="text-blue-400">Futures</strong> (1 Scanner: Pre-Move/Momentum/New-Listing + 1 Monitor, dedup global, SL sadar-leverage) dan{" "}
                <strong className="text-teal-400">Opportunity SPOT</strong> (risk-adjusted, fee-aware, cooldown).
                Total <strong className="text-white">6 autonomous agents</strong> + adaptive learning + risk dashboard.
              </p>
            </div>
            <div className="text-xs text-neutral-400 font-mono space-y-1 shrink-0">
              <div>Frontend  · Next.js 16 · TypeScript</div>
              <div>Backend   · FastAPI · Python 3.12</div>
              <div>Agents    · 6 aktif · asyncio · structlog</div>
              <div>Database  · PostgreSQL 16 · Redis 7</div>
              <div>Data      · Binance Spot + Futures REST</div>
            </div>
          </div>
          <div className="flex gap-2 mt-5 flex-wrap">
            {AGENT_PILLS.map(a => (
              <div key={a.label} className={`flex items-center gap-2 px-3 py-2 rounded-xl border ${a.color}`}>
                <span className="text-base">{a.icon}</span>
                <div>
                  <p className="text-xs font-bold text-white">{a.label}</p>
                  <p className="text-[9px] text-neutral-400">{a.sub}</p>
                </div>
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse ml-1" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <AgentsCard agentTab={agentTab} setAgentTab={setAgentTab} />
      <DataFlowCard />
      <SpotLifecycleCard />

      {/* 8 Sinyal TA */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🔭" title="8 Sinyal TA — Scanner Engine" sub="7 sinyal Futures Scanner + Taker Ratio (Spot Opp only)" />
          <Tabs tabs={Object.keys(TA_SIGNALS)} active={taTab} onChange={setTaTab} />
          {activeSig && (
            <div className="grid md:grid-cols-2 gap-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-2xl">{activeSig.icon}</span>
                  <div>
                    <p className="font-bold text-neutral-800">{taTab}</p>
                    <Badge label={`Score: ${activeSig.score}`} color="bg-teal-100 text-teal-700" />
                  </div>
                </div>
                <Code>{activeSig.formula}</Code>
              </div>
              <div className="bg-neutral-50 rounded-xl p-4 border">
                <p className="text-xs font-bold text-neutral-700 mb-2">💡 Kenapa works?</p>
                <p className="text-sm text-neutral-600 leading-relaxed">{activeSig.why}</p>
              </div>
            </div>
          )}
          <div className="mt-4 grid grid-cols-3 gap-3">
            {SCORE_RANGES.map(s => (
              <div key={s.range} className={`rounded-xl border p-3 text-center ${s.cls}`}>
                <p className="text-xl font-black">{s.range}</p>
                <p className="text-xs font-bold">{s.label}</p>
                <p className="text-[10px] opacity-70">{s.desc}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 4 Trading Styles */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="📊" title="4 Trading Styles — Futures Scanner" sub="Semua min R:R 1:3 — parameter dan timeframe berbeda" />
          <Tabs tabs={Object.keys(STYLES)} active={styleTab} onChange={setStyleTab} />
          {activeStyle && (
            <div className={`rounded-xl border bg-gradient-to-b p-4 ${activeStyle.color}`}>
              <div className="flex items-center gap-3 mb-4">
                <span className="text-3xl">{activeStyle.icon}</span>
                <div>
                  <p className="font-bold text-lg">{styleTab}</p>
                  <p className="text-xs text-neutral-500">{activeStyle.tf} · {activeStyle.dur}</p>
                </div>
                <div className="ml-auto bg-white/70 rounded-lg px-3 py-1.5 text-[10px] font-mono text-neutral-700">
                  {activeStyle.weights}
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(activeStyle.params).map(([k, v]) => (
                  <div key={k} className="bg-white/60 rounded-lg px-3 py-2">
                    <p className="text-[10px] text-neutral-500 font-semibold mb-0.5">{k}</p>
                    <p className="text-xs font-bold text-neutral-800">{v}</p>
                  </div>
                ))}
                <div className="bg-teal-100 rounded-lg px-3 py-2 border border-teal-300">
                  <p className="text-[10px] text-teal-600 font-semibold mb-0.5">Min R:R</p>
                  <p className="text-xs font-bold text-teal-800">≥ 1:3</p>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Bug Fixes & New Features */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="🐛" title="Changelog — Bug Fixes & Fitur Baru" sub="Pembaruan terbaru yang memperbaiki akurasi dan profitabilitas agents" />
          <div className="flex gap-1 bg-neutral-100 p-1 rounded-xl w-fit mb-4">
            {(["Fixed", "New Features"] as const).map(t => (
              <button key={t} onClick={() => setBugTab(t)}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  bugTab === t ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
                }`}>{t === "Fixed" ? "🐛 Bug Fixes" : "✨ Fitur Baru"}</button>
            ))}
          </div>

          {bugTab === "Fixed" && (
            <div className="space-y-2">
              {BUGS_FIXED.map(b => (
                <div key={b.id} className={`rounded-xl border p-3 ${b.sev === "🔴" ? "bg-red-50 border-red-200" : "bg-yellow-50 border-yellow-200"}`}>
                  <div className="flex items-start gap-2">
                    <span className="text-base shrink-0">{b.sev}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-bold text-neutral-800 mb-0.5">[{b.id}] {b.title}</p>
                      <p className="text-[11px] text-neutral-600 mb-1">✅ Fix: {b.fix}</p>
                      <code className="text-[10px] text-neutral-400 font-mono">{b.file}</code>
                    </div>
                  </div>
                </div>
              ))}
              <div className="mt-3 bg-neutral-900 text-white rounded-xl p-3 text-xs">
                <p className="font-bold text-teal-400 mb-2">⚠️ Root Cause Utama Balance Turun</p>
                <p className="text-neutral-300 leading-relaxed">
                  Kombinasi Bug B2 + B3 menyebabkan posisi WBTCUSDT terbuka dan tertutup dalam{" "}
                  <strong className="text-red-400">53 detik</strong> — EMA sudah bearish sebelum entry,
                  monitor langsung menembak trend_reversal. Ditambah Bug B5 (tidak ada cooldown),
                  posisi yang sama dibuka kembali 3× berturut-turut. Bug B4 menyebabkan futures
                  auto-trader membuka SHORT di regime VOLATILE → langsung SL dalam 3–44 menit.
                </p>
              </div>
            </div>
          )}

          {bugTab === "New Features" && (
            <div className="grid md:grid-cols-2 gap-3">
              {NEW_FEATURES.map(f => (
                <div key={f.title} className="bg-white border border-neutral-200 rounded-xl p-3 hover:border-teal-300 transition-colors">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-base">{f.icon}</span>
                    <p className="text-xs font-bold text-neutral-800">{f.title}</p>
                  </div>
                  <p className="text-[11px] text-neutral-600 leading-relaxed mb-2">{f.desc}</p>
                  <code className="text-[10px] text-neutral-400 font-mono">{f.file}</code>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Auto-Trade Rules */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="⚡" title="Auto-Trade Rules — Futures" sub="Kapan agent boleh buka posisi otomatis, kapan diblokir" />
          <div className="grid md:grid-cols-2 gap-4">
            <Code>{`# agents/futures/auto_trader.py

AUTO_OPEN_THRESHOLD = 72      # dasar; adaptif 70-77 per win-rate
MAX_AUTO_POSITIONS  = 6       # max posisi GLOBAL (1 wallet, semua lane)

Pool digabung dari SEMUA lane → ranking global by score →
dedup per-symbol (cross-margin = 1 posisi/koin, lane skor tertinggi menang)

BLOKIR auto-open jika:
  coin_regime == "volatile"   → blokir Pre-Move (Momentum tetap jalan)
  coin_regime == "ranging"    → threshold +5
  open_count >= 6 (global)    → sudah max posisi
  symbol sudah open di lane manapun → dedup global

BOLEH auto-open jika:
  score >= threshold adaptif (per-coin regime)
  sizing.can_open (heat/margin/notional ok)
  bukan dalam cooldown SL global`}
            </Code>
            <div className="space-y-2">
              {REGIMES.map(r => (
                <div key={r.regime} className={`rounded-xl border p-3 ${r.cls}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold capitalize">{r.regime}</span>
                    <span className="text-[10px] font-mono font-bold">{r.threshold}</span>
                  </div>
                  <p className="text-[11px] text-neutral-600 mt-0.5">{r.action}</p>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tech Stack */}
      <Card>
        <CardContent className="pt-5">
          <SectionTitle icon="⚙️" title="Tech Stack" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            {TECH_STACK.map(s => (
              <div key={s.layer} className="bg-neutral-50 border rounded-xl p-3">
                <p className="font-bold text-neutral-700 mb-2 pb-1 border-b">{s.layer}</p>
                <ul className="space-y-1">
                  {s.items.map(i => (
                    <li key={i} className="flex items-start gap-1 text-neutral-600">
                      <span className="text-teal-500 mt-0.5">·</span>{i}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

    </div>
  );
}
