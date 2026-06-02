"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface BacktestResult {
  pair: string;
  timeframe: string;
  startDate: string;
  endDate: string;
  totalTrades: number;
  winRate: number;
  profitFactor: number;
  maxDrawdown: number;
  totalReturn: number;
  status: "pending" | "running" | "completed";
}

const TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"];
const TIMEFRAMES = ["1d", "4h", "1h"];

export default function BacktestPage() {
  const [selectedPair, setSelectedPair] = useState(TRADING_PAIRS[0]);
  const [selectedTF, setSelectedTF] = useState(TIMEFRAMES[0]);
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [results, setResults] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);

  const handleRunBacktest = async () => {
    setLoading(true);
    try {
      // Simulate backtest run
      await new Promise((resolve) => setTimeout(resolve, 2000));

      const result: BacktestResult = {
        pair: selectedPair,
        timeframe: selectedTF,
        startDate,
        endDate,
        totalTrades: Math.floor(Math.random() * 100) + 20,
        winRate: Math.random() * 0.4 + 0.5,
        profitFactor: Math.random() * 2 + 1.5,
        maxDrawdown: Math.random() * 0.15 + 0.05,
        totalReturn: Math.random() * 0.3 - 0.05,
        status: "completed",
      };

      setResults(result);
    } catch (err) {
      console.error("Backtest failed:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Backtest Configuration */}
      <Card>
        <CardHeader>
          <CardTitle>Backtest Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Pair Selection */}
          <div>
            <label className="text-sm font-semibold block mb-2">Trading Pair</label>
            <select
              value={selectedPair}
              onChange={(e) => setSelectedPair(e.target.value)}
              className="w-full p-2 border rounded-lg"
            >
              {TRADING_PAIRS.map((pair) => (
                <option key={pair} value={pair}>
                  {pair}
                </option>
              ))}
            </select>
          </div>

          {/* Timeframe Selection */}
          <div>
            <label className="text-sm font-semibold block mb-2">Timeframe</label>
            <div className="grid grid-cols-3 gap-2">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  onClick={() => setSelectedTF(tf)}
                  className={`p-2 rounded-lg text-sm ${
                    selectedTF === tf ? "bg-primarygreen text-white" : "bg-neutral-100"
                  }`}
                >
                  {tf.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Date Range */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-semibold block mb-2">Start Date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full p-2 border rounded-lg"
              />
            </div>
            <div>
              <label className="text-sm font-semibold block mb-2">End Date</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full p-2 border rounded-lg"
              />
            </div>
          </div>

          {/* Run Button */}
          <button
            onClick={handleRunBacktest}
            disabled={loading}
            className="w-full p-3 bg-primarygreen text-white rounded-lg font-semibold disabled:opacity-50"
          >
            {loading ? "Running backtest..." : "Run Backtest"}
          </button>
        </CardContent>
      </Card>

      {/* Results */}
      {results && (
        <>
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>
                  {results.pair} {results.timeframe.toUpperCase()} Results
                </CardTitle>
                <Badge className="bg-green-500">Completed</Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-xs text-muted-foreground">
                {results.startDate} to {results.endDate}
              </p>

              {/* Key Metrics Grid */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="p-4 bg-neutral-100 rounded-lg">
                  <p className="text-sm text-muted-foreground">Total Trades</p>
                  <p className="text-2xl font-bold">{results.totalTrades}</p>
                </div>

                <div className="p-4 bg-green-100 rounded-lg">
                  <p className="text-sm text-muted-foreground">Win Rate</p>
                  <p className="text-2xl font-bold text-green-600">
                    {(results.winRate * 100).toFixed(1)}%
                  </p>
                </div>

                <div className="p-4 bg-blue-100 rounded-lg">
                  <p className="text-sm text-muted-foreground">Profit Factor</p>
                  <p className="text-2xl font-bold text-blue-600">
                    {results.profitFactor.toFixed(2)}
                  </p>
                </div>

                <div className="p-4 bg-red-100 rounded-lg">
                  <p className="text-sm text-muted-foreground">Max Drawdown</p>
                  <p className="text-2xl font-bold text-red-600">
                    {(results.maxDrawdown * 100).toFixed(2)}%
                  </p>
                </div>

                <div className={`p-4 rounded-lg ${results.totalReturn >= 0 ? "bg-green-100" : "bg-red-100"}`}>
                  <p className="text-sm text-muted-foreground">Total Return</p>
                  <p className={`text-2xl font-bold ${results.totalReturn >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {(results.totalReturn * 100).toFixed(2)}%
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Performance Notes */}
          <Card>
            <CardHeader>
              <CardTitle>Analysis</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="p-3 bg-neutral-50 rounded-lg">
                <p className="text-sm">
                  <span className="font-semibold">Strategy Performance:</span> The backtest shows{" "}
                  {results.winRate > 0.55
                    ? "strong profitability with above-average win rate"
                    : results.winRate > 0.5
                      ? "break-even to profitable performance"
                      : "lower profitability, consider optimizing entry/exit"}
                </p>
              </div>

              <div className="p-3 bg-neutral-50 rounded-lg">
                <p className="text-sm">
                  <span className="font-semibold">Risk Management:</span> Maximum drawdown of{" "}
                  {(results.maxDrawdown * 100).toFixed(2)}% is
                  {results.maxDrawdown < 0.1 ? " within acceptable limits" : " higher than recommended"}.
                </p>
              </div>

              <div className="p-3 bg-neutral-50 rounded-lg">
                <p className="text-sm">
                  <span className="font-semibold">Note:</span> Backtest results are based on historical data and do
                  not guarantee future performance. Market conditions may differ.
                </p>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* Information Panel */}
      <Card>
        <CardHeader>
          <CardTitle>About Backtesting</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>
            • <span className="font-semibold">Win Rate:</span> Percentage of profitable trades
          </p>
          <p>
            • <span className="font-semibold">Profit Factor:</span> Gross profit / Gross loss (1.5+ is good)
          </p>
          <p>
            • <span className="font-semibold">Max Drawdown:</span> Largest peak-to-trough decline (&lt;15% preferred)
          </p>
          <p>
            • <span className="font-semibold">Total Return:</span> Overall profit/loss percentage
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
