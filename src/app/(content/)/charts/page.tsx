"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface SRZone {
  level: number;
  strength: number;
  bounces: number;
  type: "support" | "resistance";
}

interface ChartData {
  pair: string;
  timeframe: string;
  ema13: number;
  ema21: number;
  currentPrice: number;
  supportZones: SRZone[];
  resistanceZones: SRZone[];
  trend: "bullish" | "bearish" | "neutral";
}

const TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"];
const TIMEFRAMES = ["1d", "4h", "1h"];

export default function ChartsPage() {
  const [selectedPair, setSelectedPair] = useState(TRADING_PAIRS[0]);
  const [selectedTF, setSelectedTF] = useState(TIMEFRAMES[0]);
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchChartData = async (pair: string, tf: string) => {
    setLoading(true);
    try {
      const responses = await Promise.all([
        fetch(`/api/v1/trend/${pair}/${tf}`),
        fetch(`/api/v1/support-resistance/${pair}/${tf}`),
      ]);

      const trendData = await responses[0].json();
      const srData = await responses[1].json();

      const data: ChartData = {
        pair,
        timeframe: tf,
        ema13: trendData.trend?.ema_13 ?? 0,
        ema21: trendData.trend?.ema_21 ?? 0,
        currentPrice: trendData.trend?.current_price ?? 0,
        supportZones: srData.analysis?.support_zones ?? [],
        resistanceZones: srData.analysis?.resistance_zones ?? [],
        trend: trendData.trend?.direction ?? "neutral",
      };

      setChartData(data);
    } catch (err) {
      console.error("Failed to fetch chart data:", err);
    } finally {
      setLoading(false);
    }
  };

  const handlePairChange = (pair: string) => {
    setSelectedPair(pair);
    fetchChartData(pair, selectedTF);
  };

  const handleTFChange = (tf: string) => {
    setSelectedTF(tf);
    fetchChartData(selectedPair, tf);
  };

  // Fetch initial data on mount
  useEffect(() => {
    const initData = async () => {
      await fetchChartData(selectedPair, selectedTF);
    };
    void initData();
  }, [selectedPair, selectedTF]);

  if (!chartData) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-5 gap-2">
          {TRADING_PAIRS.map((pair) => (
            <button
              key={pair}
              onClick={() => handlePairChange(pair)}
              className={`p-2 rounded-lg text-sm ${
                selectedPair === pair ? "bg-primarygreen text-white" : "bg-neutral-100"
              }`}
            >
              {pair}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-3 gap-2">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => handleTFChange(tf)}
              className={`p-2 rounded-lg text-sm ${
                selectedTF === tf ? "bg-primarygreen text-white" : "bg-neutral-100"
              }`}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>

        <Card>
          <CardContent className="pt-6 text-center">
            {loading ? "Loading chart data..." : "Select pair and timeframe to view chart"}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Pair & Timeframe Selection */}
      <div className="grid grid-cols-5 gap-2">
        {TRADING_PAIRS.map((pair) => (
          <button
            key={pair}
            onClick={() => handlePairChange(pair)}
            className={`p-2 rounded-lg text-sm ${
              selectedPair === pair ? "bg-primarygreen text-white" : "bg-neutral-100"
            }`}
          >
            {pair}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-2">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            onClick={() => handleTFChange(tf)}
            className={`p-2 rounded-lg text-sm ${
              selectedTF === tf ? "bg-primarygreen text-white" : "bg-neutral-100"
            }`}
          >
            {tf.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Chart Header */}
      <Card>
        <CardHeader>
          <CardTitle>{chartData.pair} {chartData.timeframe.toUpperCase()}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Price & Trend */}
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-neutral-100 rounded-lg">
              <p className="text-sm text-muted-foreground">Current Price</p>
              <p className="text-2xl font-bold">${chartData.currentPrice.toFixed(2)}</p>
            </div>
            <div className={`p-4 rounded-lg ${chartData.trend === "bullish" ? "bg-green-100" : "bg-red-100"}`}>
              <p className="text-sm text-muted-foreground">Trend</p>
              <p className={`text-2xl font-bold ${chartData.trend === "bullish" ? "text-green-600" : "text-red-600"}`}>
                {chartData.trend.toUpperCase()}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* EMA Indicators */}
      <Card>
        <CardHeader>
          <CardTitle>EMA Crossover</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-blue-100 rounded-lg">
              <p className="text-sm text-muted-foreground">EMA 13</p>
              <p className="text-xl font-bold text-blue-600">${chartData.ema13.toFixed(2)}</p>
            </div>
            <div className="p-4 bg-orange-100 rounded-lg">
              <p className="text-sm text-muted-foreground">EMA 21</p>
              <p className="text-xl font-bold text-orange-600">${chartData.ema21.toFixed(2)}</p>
            </div>
          </div>
          <div className="p-3 bg-neutral-50 rounded-lg text-sm">
            {chartData.ema13 > chartData.ema21 ? (
              <p className="text-green-600">✓ EMA 13 above EMA 21 (Bullish signal)</p>
            ) : (
              <p className="text-red-600">✗ EMA 13 below EMA 21 (Bearish signal)</p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Support & Resistance Zones */}
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Support Zones</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {chartData.supportZones.length === 0 ? (
                <p className="text-sm text-muted-foreground">No support zones identified</p>
              ) : (
                chartData.supportZones.map((zone, idx) => (
                  <div key={idx} className="p-3 bg-green-50 rounded-lg border border-green-200">
                    <div className="flex justify-between items-center mb-1">
                      <p className="font-bold text-green-600">${zone.level.toFixed(2)}</p>
                      <Badge className="bg-green-500">Strength: {zone.strength}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{zone.bounces} bounces</p>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Resistance Zones</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {chartData.resistanceZones.length === 0 ? (
                <p className="text-sm text-muted-foreground">No resistance zones identified</p>
              ) : (
                chartData.resistanceZones.map((zone, idx) => (
                  <div key={idx} className="p-3 bg-red-50 rounded-lg border border-red-200">
                    <div className="flex justify-between items-center mb-1">
                      <p className="font-bold text-red-600">${zone.level.toFixed(2)}</p>
                      <Badge className="bg-red-500">Strength: {zone.strength}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{zone.bounces} bounces</p>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
