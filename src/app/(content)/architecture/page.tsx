"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface Step {
  number: number;
  name: string;
  description: string;
  status: "completed" | "current" | "pending" | "future";
  layer?: string;
}

const BUILD_STEPS: Step[] = [
  {
    number: 1,
    name: "Data Pipeline",
    description: "Fetch & store Binance klines for 5 pairs × 5 timeframes",
    status: "completed",
  },
  {
    number: 2,
    name: "T1 Trend Analysis",
    description: "EMA 13/21 + trendline detection (up/down/sideways)",
    status: "completed",
    layer: "T1",
  },
  {
    number: 3,
    name: "T0 Wyckoff",
    description: "Market cycle phase detection per coin",
    status: "completed",
    layer: "T0",
  },
  {
    number: 4,
    name: "T2 Support/Resistance",
    description: "Scan 30-100 day bounce zones, cluster with ±0.5% tolerance",
    status: "completed",
    layer: "T2",
  },
  {
    number: 5,
    name: "T3 Pattern Detection",
    description: "Double bottom/top, H&S, wedges, flags, triangles",
    status: "completed",
    layer: "T3",
  },
  {
    number: 6,
    name: "T4 Trigger Signals",
    description: "Candlestick + Stochastic 5,3,3 + volume confirmation",
    status: "completed",
    layer: "T4",
  },
  {
    number: 7,
    name: "Signal Generator & Risk",
    description: "Waterfall pipeline (T0→T4), SL/TP placement, R:R >= 1:3 filter",
    status: "completed",
  },
  {
    number: 8,
    name: "Frontend Refactor",
    description: "Remove old features, setup new 6-page navigation",
    status: "completed",
  },
  {
    number: 9,
    name: "Scanner Page",
    description: "Volume heatmap, top movers, token summary table",
    status: "completed",
  },
  {
    number: 10,
    name: "Signal Feed Page",
    description: "Display signal cards with entry/SL/TP/confidence breakdown",
    status: "completed",
  },
  {
    number: 11,
    name: "Charts Page",
    description: "EMA 13/21 overlay, S/R zones, Stochastic visualization",
    status: "completed",
  },
  {
    number: 12,
    name: "Dashboard Page",
    description: "Portfolio summary, active signals, system status",
    status: "completed",
  },
  {
    number: 13,
    name: "Backtest Engine",
    description: "Run strategy on historical data, generate equity curve & metrics",
    status: "completed",
  },
  {
    number: 14,
    name: "Backtest UI Page",
    description: "Backtest config, results display, performance analysis",
    status: "completed",
  },
  {
    number: 15,
    name: "Settings Page",
    description: "Risk config, TA parameters, API key setup",
    status: "pending",
  },
  {
    number: 16,
    name: "Onchain Layer (FUTURE)",
    description: "DexScreener + GoPlus integration (after Steps 1-15 proven)",
    status: "future",
  },
];

const getStatusColor = (status: string) => {
  switch (status) {
    case "completed":
      return "bg-green-100 text-green-800 border-green-300";
    case "current":
      return "bg-blue-100 text-blue-800 border-blue-300";
    case "pending":
      return "bg-yellow-100 text-yellow-800 border-yellow-300";
    case "future":
      return "bg-gray-100 text-gray-800 border-gray-300";
    default:
      return "bg-neutral-100 text-neutral-800";
  }
};

const getStatusBadge = (status: string) => {
  switch (status) {
    case "completed":
      return <Badge className="bg-green-500">✓ Done</Badge>;
    case "current":
      return <Badge className="bg-blue-500">● Current</Badge>;
    case "pending":
      return <Badge className="bg-yellow-500">⏳ Pending</Badge>;
    case "future":
      return <Badge className="bg-gray-500">⊘ Future</Badge>;
    default:
      return null;
  }
};

export default function ArchitecturePage() {
  const completed = BUILD_STEPS.filter((s) => s.status === "completed").length;
  const total = BUILD_STEPS.length;
  const progressPercent = (completed / total) * 100;

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card className="bg-gradient-to-r from-primarygreen to-teal-500 text-white border-0">
        <CardContent className="pt-6">
          <h1 className="text-3xl font-bold mb-2">Build Order Architecture</h1>
          <p className="text-sm opacity-90">14-step implementation plan for crypto trading agent</p>
        </CardContent>
      </Card>

      {/* Progress */}
      <Card>
        <CardHeader>
          <CardTitle>Implementation Progress</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-semibold">{completed} of {total} steps completed</span>
            <span className="text-2xl font-bold text-primarygreen">{progressPercent.toFixed(0)}%</span>
          </div>
          <div className="w-full bg-neutral-200 rounded-full h-3 overflow-hidden">
            <div
              className="bg-primarygreen h-full transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </CardContent>
      </Card>

      {/* Steps Grid */}
      <div className="space-y-3">
        {BUILD_STEPS.map((step) => (
          <Card
            key={step.number}
            className={`border-l-4 ${
              step.status === "completed"
                ? "border-l-green-500 bg-green-50"
                : step.status === "current"
                  ? "border-l-blue-500 bg-blue-50"
                  : step.status === "pending"
                    ? "border-l-yellow-500 bg-yellow-50"
                    : "border-l-gray-500 bg-gray-50"
            }`}
          >
            <CardContent className="pt-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="text-2xl font-bold text-muted-foreground w-8">
                      {step.number}
                    </span>
                    <h3 className="text-lg font-semibold">{step.name}</h3>
                    {step.layer && (
                      <Badge variant="outline" className="text-xs">
                        {step.layer}
                      </Badge>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground ml-11">{step.description}</p>
                </div>
                <div className="flex-shrink-0">{getStatusBadge(step.status)}</div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Legend */}
      <Card>
        <CardHeader>
          <CardTitle>Status Legend</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-green-500"></div>
            <span className="text-sm">Completed</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-blue-500"></div>
            <span className="text-sm">Current</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
            <span className="text-sm">Pending</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-gray-500"></div>
            <span className="text-sm">Future</span>
          </div>
        </CardContent>
      </Card>

      {/* TA Pipeline Info */}
      <Card>
        <CardHeader>
          <CardTitle>TA Pipeline Waterfall</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>Signal generation follows strict waterfall with gating:</p>
          <div className="bg-neutral-50 p-3 rounded-lg font-mono text-xs space-y-1">
            <div>T0 (Wyckoff) ─┬─ GATE ─┐</div>
            <div>T1 (Trend)   ─┼─ GATE ─┼─ COMBINE</div>
            <div>T2 (S/R)     ─┼─ GATE ─┼─ COMBINE ─ FILTER</div>
            <div>T3 (Pattern) ─┼─ GATE ─┼─ COMBINE ─ (R:R &gt;= 1:3)</div>
            <div>T4 (Trigger) ─┴─ GATE ─┘</div>
          </div>
          <p className="mt-3">
            <strong>Timeframe Hierarchy:</strong> 1W (direction) → 1D (confirm) → 4H (zones) → 1H (pattern) → 15m (execute)
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
