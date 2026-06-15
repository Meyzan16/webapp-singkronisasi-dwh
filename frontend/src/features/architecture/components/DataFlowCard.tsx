import { Card, CardContent } from "@/components/ui/card";
import { Code, SectionTitle } from "./primitives";

const SYSTEMS = [
  {
    dot: "bg-blue-500",
    label: "Sistem 1 — Futures Scanner (2 Agents)",
    color: "text-blue-700",
    note: "📌 Fully automatic — tidak butuh interaksi user",
    code: `Binance Futures API (150 pair + new listings)
         │
         ▼  ⏱ setiap 2 menit
  ┌──────────────────────────┐
  │   FUTURES SCANNER (1)     │
  │  ├ Pre-Move (a1+a2)       │  BB squeeze · akumulasi · OI
  │  ├ Momentum  (a3)         │  change 5-20% · vol · breakout
  │  └ New-Listing            │  onboardDate ≤ 14h
  └──────────┬───────────────┘
             ▼  ranking GLOBAL + setup_type
   dedup per-symbol (cross-margin = 1 posisi/koin)
             ▼  SL floor sadar-leverage · sizing 1 wallet
  paper_trades (style=futures_agent1/2/3 utk win-rate)
         │
         ▼  ⏱ setiap 120 detik
  FUTURES MONITOR (1) → wick 1m · SL+ · liq guard
         │
         ▼
  Weight Updater → recency 30d + warm-start dari DB
         │
         ▼
  History — Futures tab · Win rate per strategi · P&L`,
  },
  {
    dot: "bg-teal-500",
    label: "Sistem 2 — Opportunity SPOT (4 Layer)",
    color: "text-teal-700",
    note: "📌 User memilih koin & buka posisi sendiri",
    code: `Binance Spot API (100 pair USDT)
         │
         ▼  ⏱ setiap 15 menit
Layer 1: Spot Opp Scanner
         │  9 sinyal · top-30 kandidat
         │  → WS broadcast ke frontend
         ▼
Layer 2: Coin Analyzer (on-click user)
         │  ATR · depth ratio · resistance
         │  → Entry/SL/TP1/TP2/TP3
         ▼
Layer 3: User → "Buka Posisi SPOT"
         │  validasi entry · 1 pos/koin
         │  → simpan paper_trades (status=open)
         ▼
Layer 3b: Spot Monitor (60s)
         │  → TP hit → status='tp'
         │  → SL hit → status='sl'
         │  → TP1 hit → tp1_hit=True (tetap open)
         ▼
Layer 4: History — Spot Opp tab
         win rate · avg P&L · analytics`,
  },
];

const SUMMARY = [
  { icon: "🤖", title: "Agents (background)", color: "bg-purple-50 border-purple-200",
    items: [
      "Futures Scanner — 1 agent, lane Pre-Move/Momentum/New-Listing",
      "Futures Monitor — 1 agent, wick 1m · SL+ · liq guard · 120s",
      "Weight Updater — recency 30d + warm-start dari DB",
      "Spot Opp Scanner — momentum + rotation, top-30, WS",
      "Spot Monitor — auto TP/SL, max-age 7d, flag TP1",
    ]},
  { icon: "⚙️", title: "Backend (API layer)", color: "bg-teal-50 border-teal-200",
    items: [
      "REST: /futures/ · /opportunity/ · /history/",
      "REST: /market/binance-status · /market/context",
      "WebSocket: /ws/futures · /ws/opportunity",
      "TA Engine (T0–T4) untuk deep analysis",
      "Adaptive signal weights (signal_weights table)",
      "/health endpoint — semua agent status",
    ]},
  { icon: "🖥", title: "Frontend (consumer)", color: "bg-blue-50 border-blue-200",
    items: [
      "Dashboard: posisi terbuka + scanner status",
      "Futures Scanner: WS live · Agent1+2 results",
      "Spot Opportunity: WS live + CoinModal (Layer 2)",
      "History: Spot tab + Futures tab + analytics",
      "System Health: monitoring real-time semua agent",
      "Architecture: docs teknis (halaman ini)",
    ]},
];

export function DataFlowCard() {
  return (
    <Card>
      <CardContent className="pt-5">
        <SectionTitle icon="🔄" title="Alur Data — 2 Sistem Independen" sub="Futures (auto-log oleh agents) vs Opportunity SPOT (user-driven)" />

        <div className="grid md:grid-cols-2 gap-4">
          {SYSTEMS.map(sys => (
            <div key={sys.label}>
              <div className="flex items-center gap-2 mb-2">
                <span className={`w-2 h-2 rounded-full ${sys.dot}`} />
                <p className={`font-bold text-sm ${sys.color}`}>{sys.label}</p>
              </div>
              <Code>{sys.code}</Code>
              <p className="text-xs text-neutral-500 mt-2">{sys.note}</p>
            </div>
          ))}
        </div>

        <div className="mt-4 grid md:grid-cols-3 gap-3 text-xs">
          {SUMMARY.map(s => (
            <div key={s.title} className={`rounded-xl border p-3 ${s.color}`}>
              <p className="font-bold text-neutral-800 mb-2 flex items-center gap-1.5">
                <span>{s.icon}</span>{s.title}
              </p>
              <ul className="space-y-1">
                {s.items.map(i => (
                  <li key={i} className="text-neutral-600 flex items-start gap-1">
                    <span className="text-neutral-400">·</span>{i}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
