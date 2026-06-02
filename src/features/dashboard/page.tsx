"use client";
import { Card, CardContent } from "@/components/ui/card";
import { SpotPositions } from "./components/SpotPositions";
import { FuturesPositions } from "./components/FuturesPositions";
import { FuturesMarket } from "./components/FuturesMarket";
import { SystemStatusCard } from "./components/SystemStatusCard";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <Card className="bg-gradient-to-r from-primarygreen to-teal-500 text-white border-0">
        <CardContent className="pt-6">
          <h1 className="text-3xl font-bold mb-2">AI Trading Agent</h1>
          <p className="text-sm opacity-90">
            Multi-timeframe technical analysis • 5 trading pairs • Wyckoff + EMA + S/R zones
          </p>
        </CardContent>
      </Card>

      {/* Spot + Futures Positions side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SpotPositions />
        <FuturesPositions />
      </div>

      {/* Futures Market — all coins 24h change */}
      <FuturesMarket />

      {/* System Status */}
      <SystemStatusCard />
    </div>
  );
}
