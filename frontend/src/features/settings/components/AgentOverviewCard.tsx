"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const AGENTS = [
  {
    id: "A1", name: "Pre-Gainer",
    desc: "Pre-pump via Wyckoff accumulation + volume z-score + OI acceleration",
    rr: "1:3", color: "bg-blue-50 border-blue-200 text-blue-900",
  },
  {
    id: "A2", name: "Accumulation",
    desc: "Smart money accumulation via multi-TF EMA trend + BB squeeze",
    rr: "1:3", color: "bg-purple-50 border-purple-200 text-purple-900",
  },
  {
    id: "A3", name: "Momentum",
    desc: "Trend continuation pada coin yang sudah bergerak dengan konfirmasi",
    rr: "1:3", color: "bg-teal-50 border-teal-200 text-teal-900",
  },
  {
    id: "BM", name: "Big Mover",
    desc: "Breakout cepat pada event volume tinggi (±5% threshold)",
    rr: "1:2", color: "bg-orange-50 border-orange-200 text-orange-900",
  },
];

const SYSTEM_ROWS = [
  { label: "Universe",        value: "100 USDT Futures pairs" },
  { label: "Scan interval",   value: "Setiap 15 menit" },
  { label: "TA pipeline",     value: "7-signal engine (T0–T4)" },
  { label: "Leverage model",  value: "Dinamis — ATR% + skor sinyal" },
  { label: "Sizing model",    value: "Paper balance weighted, per-trade" },
  { label: "Dedup rule",      value: "1 posisi terbuka per coin (global, semua lane)" },
];

const RISK_ROWS = [
  { label: "Circuit breaker", value: "Drawdown > 15% → semua lane berhenti" },
  { label: "Hysteresis",      value: "Buka kembali saat drawdown < 8%" },
  { label: "RAR gate",        value: "Sharpe proxy < −0.5 setelah ≥10 trade tertutup" },
  { label: "Lane auto-pause", value: "WR < 35% dalam 20 trade rolling → pause 24 jam" },
  { label: "Wallet scaling",  value: "Threshold DD adaptif berdasarkan ukuran wallet" },
];

function InfoTable({ rows }: { rows: { label: string; value: string }[] }) {
  return (
    <div className="rounded-xl border border-neutral-200 overflow-hidden">
      {rows.map((row, i) => (
        <div
          key={row.label}
          className={`flex items-start gap-3 px-4 py-2.5 ${i % 2 !== 0 ? "bg-neutral-50" : ""}`}
        >
          <span className="text-xs text-neutral-400 w-36 shrink-0 pt-px">{row.label}</span>
          <span className="text-xs font-semibold text-neutral-800">{row.value}</span>
        </div>
      ))}
    </div>
  );
}

export function AgentOverviewCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>System Configuration</CardTitle>
        <p className="text-xs text-neutral-500 mt-1">
          Parameter operasi dikelola otomatis oleh engine.
          Leverage, sizing, dan risk gate dihitung per-trade berdasarkan ATR dan skor sinyal.
        </p>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Active agents */}
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wider text-neutral-400 mb-3">
            Active Agents
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {AGENTS.map((a) => (
              <div key={a.id} className={`rounded-xl border p-3 ${a.color}`}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-mono text-[11px] font-black bg-white/60 px-1.5 py-0.5 rounded">
                    {a.id}
                  </span>
                  <span className="text-sm font-bold">{a.name}</span>
                  <Badge className="ml-auto text-[10px] bg-white/50 border-current/20 border text-current">
                    Min R:R {a.rr}
                  </Badge>
                </div>
                <p className="text-xs opacity-75 leading-snug">{a.desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* System parameters */}
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wider text-neutral-400 mb-3">
            System Parameters
          </p>
          <InfoTable rows={SYSTEM_ROWS} />
        </div>

        {/* Risk gate */}
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wider text-neutral-400 mb-3">
            Auto Risk Gate
          </p>
          <InfoTable rows={RISK_ROWS} />
        </div>

        <div className="bg-blue-50 border border-blue-200 p-3 rounded-lg">
          <p className="text-xs text-blue-900">
            <strong>Paper Trading Mode:</strong> Semua posisi adalah simulasi — tidak ada uang nyata
            yang ditransaksikan. Gunakan tab{" "}
            <a href="/history" className="underline font-semibold">History</a> untuk melihat hasil
            dan win rate per strategi.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
