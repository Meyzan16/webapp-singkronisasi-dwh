"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { MetricsCard, SystemStatusCard, OpenPositions } from "./components";

export default function DashboardPage() {
  const [stats] = useState({
    totalSignals: 0,
    activeSignals: 0,
    buySignals: 0,
    sellSignals: 0,
    avgConfidence: 0,
    avgRR: 0,
  });

  return (
    <div className="space-y-6">
      <Card className="bg-gradient-to-r from-primarygreen to-teal-500 text-white border-0">
        <CardContent className="pt-6">
          <h1 className="text-3xl font-bold mb-2">AI Trading Agent</h1>
          <p className="text-sm opacity-90">Multi-timeframe technical analysis • 5 trading pairs • Wyckoff + EMA + S/R zones</p>
        </CardContent>
      </Card>

      <MetricsCard stats={stats} />
      <OpenPositions />
      <SystemStatusCard />
    </div>
  );
}
