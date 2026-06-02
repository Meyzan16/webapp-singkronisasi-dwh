"use client";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

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

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Total Signals</p><p className="text-3xl font-bold">{stats.totalSignals}</p></CardContent></Card>
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Active Signals</p><p className="text-3xl font-bold text-primarygreen">{stats.activeSignals}</p></CardContent></Card>
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Avg Confidence</p><p className="text-3xl font-bold">{(stats.avgConfidence * 100).toFixed(0)}%</p></CardContent></Card>
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Buy Signals</p><p className="text-3xl font-bold text-green-600">{stats.buySignals}</p></CardContent></Card>
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Sell Signals</p><p className="text-3xl font-bold text-red-600">{stats.sellSignals}</p></CardContent></Card>
        <Card><CardContent className="pt-6"><p className="text-sm text-muted-foreground">Avg Risk/Reward</p><p className="text-3xl font-bold">1:{stats.avgRR.toFixed(2)}</p></CardContent></Card>
      </div>

      <Card>
        <CardHeader><CardTitle>System Status</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
            <span className="text-sm font-medium">Data Pipeline</span><Badge className="bg-green-500">Online</Badge>
          </div>
          <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
            <span className="text-sm font-medium">TA Engine</span><Badge className="bg-green-500">Running</Badge>
          </div>
          <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
            <span className="text-sm font-medium">Signal Generator</span><Badge className="bg-green-500">Active</Badge>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
