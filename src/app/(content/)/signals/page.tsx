"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface SignalCard {
  pair: string;
  timeframe: string;
  signal: "buy" | "sell" | null;
  entry: number;
  stopLoss: number;
  takeProfit: number;
  confidence: number;
  riskReward: number;
  reason: string;
  wyckoffPhase?: string;
  trend?: string;
  pattern?: string;
  trigger?: string;
  timestamp: string;
}

const TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"];
const TIMEFRAMES = ["1d", "4h", "1h"];

export default function SignalFeedPage() {
  const [signals, setSignals] = useState<SignalCard[]>([]);
  const [filter, setFilter] = useState<"all" | "buy" | "sell">("all");
  const [error, setError] = useState<string | null>(null);

  const fetchSignals = async () => {
    try {
      setError(null);
      const allSignals: SignalCard[] = [];

      for (const pair of TRADING_PAIRS) {
        for (const tf of TIMEFRAMES) {
          try {
            const response = await fetch(`/api/v1/signals/${pair}/${tf}`);
            if (response.ok) {
              const result = await response.json();
              if (result.signal) {
                allSignals.push({
                  pair,
                  timeframe: tf,
                  signal: result.signal.signal,
                  entry: result.signal.entry,
                  stopLoss: result.signal.stop_loss,
                  takeProfit: result.signal.take_profit,
                  confidence: result.signal.confidence,
                  riskReward: result.signal.risk_reward_ratio,
                  reason: result.signal.reasoning,
                  wyckoffPhase: result.signal.wyckoff_phase,
                  trend: result.signal.trend,
                  pattern: result.signal.pattern,
                  trigger: result.signal.trigger,
                  timestamp: new Date().toISOString(),
                });
              }
            }
          } catch (err) {
            console.error(`Failed to fetch signal for ${pair}/${tf}:`, err);
          }
        }
      }

      setSignals(allSignals);
    } catch (err) {
      setError("Failed to fetch signals");
      console.error(err);
    }
  };

  useEffect(() => {
    const initSignals = async () => {
      await fetchSignals();
    };
    void initSignals();
    const interval = setInterval(() => {
      void initSignals();
    }, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, []);

  const filteredSignals = signals.filter((s) => filter === "all" || s.signal === filter);
  const buySignals = signals.filter((s) => s.signal === "buy").length;
  const sellSignals = signals.filter((s) => s.signal === "sell").length;

  return (
    <div className="space-y-6">
      {/* Signal Stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <p className="text-sm text-muted-foreground">Total Signals</p>
              <p className="text-3xl font-bold">{signals.length}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <p className="text-sm text-muted-foreground">Buy Signals</p>
              <p className="text-3xl font-bold text-green-600">{buySignals}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <p className="text-sm text-muted-foreground">Sell Signals</p>
              <p className="text-3xl font-bold text-red-600">{sellSignals}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filter Buttons */}
      <div className="flex gap-2">
        <button
          onClick={() => setFilter("all")}
          className={`px-4 py-2 rounded-lg ${filter === "all" ? "bg-primarygreen text-white" : "bg-neutral-100"}`}
        >
          All
        </button>
        <button
          onClick={() => setFilter("buy")}
          className={`px-4 py-2 rounded-lg ${filter === "buy" ? "bg-green-500 text-white" : "bg-neutral-100"}`}
        >
          Buy Only
        </button>
        <button
          onClick={() => setFilter("sell")}
          className={`px-4 py-2 rounded-lg ${filter === "sell" ? "bg-red-500 text-white" : "bg-neutral-100"}`}
        >
          Sell Only
        </button>
      </div>

      {/* Signal Cards */}
      <div className="space-y-4">
        {filteredSignals.length === 0 ? (
          <Card>
            <CardContent className="pt-6 text-center text-muted-foreground">
              No signals at this time
            </CardContent>
          </Card>
        ) : (
          filteredSignals.map((signal, idx) => (
            <Card key={idx} className={signal.signal === "buy" ? "border-green-500" : "border-red-500"}>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-lg">
                      {signal.pair} {signal.timeframe.toUpperCase()}
                    </CardTitle>
                    <p className="text-xs text-muted-foreground mt-1">{signal.timestamp}</p>
                  </div>
                  <div className="text-right">
                    <Badge className={signal.signal === "buy" ? "bg-green-500" : "bg-red-500"}>
                      {signal.signal?.toUpperCase()}
                    </Badge>
                    <p className="text-sm font-bold mt-2">Confidence: {(signal.confidence * 100).toFixed(0)}%</p>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Entry/SL/TP */}
                <div className="grid grid-cols-3 gap-4">
                  <div className="p-3 bg-neutral-100 rounded-lg">
                    <p className="text-xs text-muted-foreground">Entry</p>
                    <p className="text-lg font-bold">${signal.entry.toFixed(2)}</p>
                  </div>
                  <div className="p-3 bg-red-100 rounded-lg">
                    <p className="text-xs text-muted-foreground">Stop Loss</p>
                    <p className="text-lg font-bold text-red-600">${signal.stopLoss.toFixed(2)}</p>
                  </div>
                  <div className="p-3 bg-green-100 rounded-lg">
                    <p className="text-xs text-muted-foreground">Take Profit</p>
                    <p className="text-lg font-bold text-green-600">${signal.takeProfit.toFixed(2)}</p>
                  </div>
                </div>

                {/* Risk/Reward */}
                <div className="p-3 bg-blue-100 rounded-lg">
                  <p className="text-xs text-muted-foreground">Risk/Reward Ratio</p>
                  <p className="text-lg font-bold text-blue-600">1:{signal.riskReward.toFixed(2)}</p>
                </div>

                {/* Analysis Breakdown */}
                <div className="space-y-2 p-3 bg-neutral-50 rounded-lg">
                  <p className="text-sm font-semibold">Analysis:</p>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    {signal.wyckoffPhase && (
                      <p>
                        <span className="text-muted-foreground">Wyckoff:</span> {signal.wyckoffPhase}
                      </p>
                    )}
                    {signal.trend && (
                      <p>
                        <span className="text-muted-foreground">Trend:</span> {signal.trend}
                      </p>
                    )}
                    {signal.pattern && (
                      <p>
                        <span className="text-muted-foreground">Pattern:</span> {signal.pattern}
                      </p>
                    )}
                    {signal.trigger && (
                      <p>
                        <span className="text-muted-foreground">Trigger:</span> {signal.trigger}
                      </p>
                    )}
                  </div>
                </div>

                {/* Reasoning */}
                <div className="p-3 bg-neutral-50 rounded-lg">
                  <p className="text-sm font-semibold mb-2">Reasoning:</p>
                  <p className="text-sm text-muted-foreground">{signal.reason}</p>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {error && <div className="text-red-600 text-sm">{error}</div>}
    </div>
  );
}
