"use client";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, LiveBadge, SectionTitle, SourceBadge } from "./primitives";
import { ADAPTIVE_LEARNING, TECH_STACK } from "../data";
import { useAgentConfig } from "../hooks/useAgentConfig";
import { useAgentConfigDbKeys } from "../hooks/useAgentConfigDbKeys";

// ─── LEARNING OVERVIEW ───────────────────────────────────────────────────────
function LearnFlow() {
  const steps = [
    { emoji: "✅", label: "Trade selesai (TP/SL/expired)" },
    { emoji: "🔍", label: "Ambil semua sinyal aktif saat entry" },
    { emoji: "📊", label: "Hitung weighted WR per sinyal" },
    { emoji: "⚖️", label: "Update weight = target × confidence" },
    { emoji: "📉", label: "Time decay (half-life 7/14 hari)" },
    { emoji: "🔄", label: "Scan berikutnya pakai weight baru" },
  ];

  return (
    <div className="mb-6">
      <SectionTitle icon="🧠" title="Adaptive Signal Weighting" sub="Setiap trade yang selesai langsung memperbarui bobot sinyal untuk scan berikutnya" />
      <div className="bg-neutral-900 rounded-xl p-4 mb-4">
        <div className="flex flex-wrap gap-1 items-center">
          {steps.map((s, i) => (
            <div key={i} className="flex items-center gap-1">
              <div className="flex items-center gap-1.5 bg-neutral-800 rounded-lg px-3 py-2">
                <span>{s.emoji}</span>
                <span className="text-xs text-neutral-200">{s.label}</span>
              </div>
              {i < steps.length - 1 && <span className="text-neutral-600 text-sm">→</span>}
            </div>
          ))}
        </div>
      </div>
      <p className="text-xs text-neutral-500 bg-neutral-50 border rounded-xl p-3">{ADAPTIVE_LEARNING.overview}</p>
    </div>
  );
}

// ─── WEIGHT FORMULA ──────────────────────────────────────────────────────────
function WeightFormula() {
  const { data, loading } = useAgentConfig();
  const dbKeys = useAgentConfigDbKeys();
  const live = data?.learning;

  const wrColor: Record<string, string> = {
    "↑ boost 50%":   "bg-green-50 border-green-200 text-green-800",
    "↑ boost 20%":   "bg-teal-50 border-teal-200 text-teal-800",
    "neutral":       "bg-neutral-50 border-neutral-200 text-neutral-600",
    "↓ penalize 30%": "bg-red-50 border-red-200 text-red-800",
  };

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-4">
        <SectionTitle icon="⚖️" title="Weight Update Formula" sub="Laplace smoothing cegah over-fit, confidence scaling dari sample size" />
        <LiveBadge live={!!live} loading={loading} />
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <div className="space-y-3">
          {/* WR → target table */}
          <div className="bg-neutral-50 border rounded-xl p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Win Rate → Target Weight</p>
            <div className="space-y-1.5">
              {ADAPTIVE_LEARNING.weightFormula.map(w => (
                <div key={w.wr} className={`flex items-center justify-between rounded-lg border px-3 py-2 ${wrColor[w.note] ?? "bg-neutral-50 border-neutral-200"}`}>
                  <span className="text-xs font-bold">WR {w.wr}</span>
                  <div className="text-right">
                    <span className="text-xs font-mono font-bold">× {w.target}</span>
                    <span className="text-[10px] ml-2 opacity-70">{w.note}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Decay */}
          <div className="bg-neutral-50 border rounded-xl p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Time Decay</p>
            <div className="space-y-1.5 text-xs">
              <div className="flex justify-between items-center">
                <span className="text-neutral-600 flex items-center">Spot half-life<SourceBadge dbKey="learning.decay_half_life_days" dbKeys={dbKeys} /></span>
                <Badge label={live ? `${live.decay_half_life_days} hari` : ADAPTIVE_LEARNING.spotDecay.halfLife} color="bg-teal-50 text-teal-700" />
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">Futures half-life</span>
                <Badge label={ADAPTIVE_LEARNING.futuresDecay.halfLife} color="bg-blue-50 text-blue-700" />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-neutral-600 flex items-center">Window<SourceBadge dbKey="learning.training_window_days" dbKeys={dbKeys} /></span>
                <Badge label={live ? `${live.training_window_days} hari` : ADAPTIVE_LEARNING.spotDecay.window} color="bg-neutral-100 text-neutral-700" />
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-600">Min Sample</span>
                <Badge label={`${ADAPTIVE_LEARNING.minSample} trades`} color="bg-neutral-100 text-neutral-700" />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-neutral-600 flex items-center">Step Cap<SourceBadge dbKey="learning.step_cap" dbKeys={dbKeys} /></span>
                <Badge label={live?.step_cap != null ? `${(live.step_cap * 100).toFixed(0)}%/run` : ADAPTIVE_LEARNING.stepCap} color="bg-orange-50 text-orange-700" />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-neutral-600 flex items-center">Cross-Agent Blend<SourceBadge dbKey="learning.cross_blend" dbKeys={dbKeys} /></span>
                <Badge label={live ? `${live.cross_agent?.blend_pct}%` : "30%"} color="bg-purple-50 text-purple-700" />
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-3">
          {/* Formulas */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Implementasi</p>
            <pre className="bg-neutral-900 text-green-400 text-[10px] font-mono p-3 rounded-xl overflow-x-auto leading-relaxed">
{`# Laplace Smoothing (cegah over-fit sample kecil)
${ADAPTIVE_LEARNING.laplace}

# Confidence Scaling (makin banyak data makin percaya)
${ADAPTIVE_LEARNING.confidence}

# Final weight update
new_weight = old_weight × (1 − step_cap)
           + target_weight × confidence × step_cap`}
            </pre>
          </div>

          {/* Coin WR Bonus */}
          <div className="bg-neutral-50 border rounded-xl p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Per-Coin Historical Bonus</p>
            <div className="space-y-1.5">
              {ADAPTIVE_LEARNING.coinWRBonus.map((b, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="text-neutral-600">{b.condition}</span>
                  <Badge label={b.bonus} color={b.bonus.startsWith("+") ? "bg-teal-50 text-teal-700" : b.bonus.startsWith("-") ? "bg-red-50 text-red-600" : "bg-neutral-100 text-neutral-500"} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── AUTO THRESHOLD ───────────────────────────────────────────────────────────
function ThresholdTable() {
  return (
    <div className="mb-6">
      <SectionTitle icon="📊" title="Futures Auto-Threshold" sub="Threshold min_score dan auto_open berubah otomatis sesuai win rate historis" />
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="bg-neutral-100">
              <th className="text-left px-3 py-2 font-bold text-neutral-700 rounded-tl-lg">Kondisi</th>
              <th className="text-center px-3 py-2 font-bold text-neutral-700">Min Score</th>
              <th className="text-center px-3 py-2 font-bold text-neutral-700 rounded-tr-lg">Auto-Open</th>
            </tr>
          </thead>
          <tbody>
            {ADAPTIVE_LEARNING.futuresThresholds.map((t, i) => (
              <tr key={i} className={i % 2 === 0 ? "bg-white" : "bg-neutral-50"}>
                <td className="px-3 py-2 text-neutral-700">
                  {t.condition}
                  {t.note && <span className="ml-1.5 text-[10px] text-neutral-400">({t.note})</span>}
                </td>
                <td className="px-3 py-2 text-center font-bold text-blue-700">{t.minScore}</td>
                <td className="px-3 py-2 text-center font-bold text-teal-700">{t.autoThreshold}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── COIN BLACKLIST ───────────────────────────────────────────────────────────
function BlacklistSection() {
  const bl = ADAPTIVE_LEARNING.coinBlacklist;
  return (
    <div>
      <SectionTitle icon="🚫" title="Coin Blacklist" sub="Cegah agent terus masuk ke koin yang lagi broken" />
      <div className="bg-red-50 border border-red-200 rounded-xl p-4">
        <div className="grid md:grid-cols-3 gap-4 text-xs">
          <div>
            <p className="font-bold text-red-800 mb-1">Trigger</p>
            <p className="text-red-700">{bl.trigger}</p>
          </div>
          <div>
            <p className="font-bold text-red-800 mb-1">Action</p>
            <p className="text-red-700">{bl.action}</p>
          </div>
          <div>
            <p className="font-bold text-red-800 mb-1">Alasan</p>
            <p className="text-red-700">{bl.why}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── TECH SECTION ─────────────────────────────────────────────────────────────
function TechStackSection() {
  return (
    <div>
      <SectionTitle icon="⚙️" title="Tech Stack" sub="Monorepo: Next.js (frontend) · FastAPI (backend) · Python asyncio (agents)" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {TECH_STACK.map(s => (
          <div key={s.layer} className={`rounded-xl border p-4 ${s.color}`}>
            <p className="text-sm font-bold text-neutral-800 mb-3 flex items-center gap-2">
              <span>{s.icon}</span> {s.layer}
            </p>
            <ul className="space-y-1.5">
              {s.items.map(item => (
                <li key={item} className="text-xs text-neutral-700 flex items-start gap-1.5">
                  <span className="text-teal-500 mt-0.5 shrink-0">·</span> {item}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Data flow */}
      <div className="mt-4 bg-neutral-900 text-neutral-300 rounded-xl p-4 text-[11px] font-mono">
        <p className="text-teal-400 font-bold mb-2">Data Flow</p>
        <pre className="whitespace-pre leading-relaxed">{`Binance Futures/Spot REST API
  │
  ▼  every 3 min (spot) / 5 min (futures)
Scanner Agent (asyncio background loop)
  │
  ├── agents/scanner/store.py  ← in-memory cache → Scanner API (read-only)
  │
  └── paper_trades (PostgreSQL) ← agents/paper_trader/trader.py
        │
        └── Monitor Agent (every 60s spot / 2 min futures)
              │
              ├── TP/SL hit → close → update paper_trades
              └── Signal weights update → adaptive learning`}
        </pre>
      </div>
    </div>
  );
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────
export function LearningSection() {
  return (
    <div className="space-y-2">
      <Card>
        <CardContent className="pt-5">
          <LearnFlow />
          <WeightFormula />
          <ThresholdTable />
          <BlacklistSection />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-5">
          <TechStackSection />
        </CardContent>
      </Card>
    </div>
  );
}
