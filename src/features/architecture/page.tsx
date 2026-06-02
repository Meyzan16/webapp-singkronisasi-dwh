"use client";

import { Card, CardContent } from "@/components/ui/card";
import { StepCard, ProgressBar, PipelineDiagram } from "./components";

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

export default function ArchitecturePage() {
  const completed = BUILD_STEPS.filter((s) => s.status === "completed").length;
  const total = BUILD_STEPS.length;

  return (
    <div className="space-y-6">
      <Card className="bg-gradient-to-r from-primarygreen to-teal-500 text-white border-0">
        <CardContent className="pt-6">
          <h1 className="text-3xl font-bold mb-2">Build Order Architecture</h1>
          <p className="text-sm opacity-90">
            14-step implementation plan for crypto trading agent
          </p>
        </CardContent>
      </Card>

      <ProgressBar completed={completed} total={total} />

      <div className="space-y-3">
        {BUILD_STEPS.map((step) => (
          <StepCard key={step.number} step={step} />
        ))}
      </div>

      <Card>
        <CardContent className="pt-6 space-y-3">
          <h3 className="font-semibold">Status Legend</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
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
          </div>
        </CardContent>
      </Card>

      <PipelineDiagram />
    </div>
  );
}
