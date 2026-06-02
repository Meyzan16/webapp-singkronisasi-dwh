"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface PairData {
  pair: string;
  timeframe: string;
  currentPrice: number;
  change24h: number;
  volume24h: number;
  volumeSpike: boolean;
  takerBuyPressure?: number;
}

const TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"];

export default function ScannerPage() {
  const [pairData, setPairData] = useState<PairData[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchKlineData = async () => {
    try {
      setError(null);

      // Fetch klines data from backend for 1H timeframe
      const data: PairData[] = [];

      interface Kline {
        open: string;
        close: string;
        volume: string;
      }

      for (const pair of TRADING_PAIRS) {
        try {
          const response = await fetch(`/api/v1/klines/${pair}/1h?limit=100`);
          if (response.ok) {
            const result = await response.json();
            const klines: Kline[] = result.klines;

            if (klines && klines.length > 0) {
              const latest = klines[klines.length - 1];

              // Calculate 24h change
              const change24h = ((parseFloat(latest.close) - parseFloat(klines[0].close)) / parseFloat(klines[0].close)) * 100;

              // Calculate average volume
              const volumesLast7 = klines.slice(-7).map((k) => parseFloat(k.volume));
              const avgVolume = volumesLast7.reduce((a: number, b: number) => a + b, 0) / volumesLast7.length;
              const currentVolume = parseFloat(latest.volume);
              const volumeSpike = currentVolume > avgVolume * 1.5;

              data.push({
                pair,
                timeframe: "1h",
                currentPrice: parseFloat(latest.close),
                change24h,
                volume24h: currentVolume,
                volumeSpike,
              });
            }
          }
        } catch (err) {
          console.error(`Failed to fetch data for ${pair}:`, err);
        }
      }

      setPairData(data);
    } catch (err) {
      setError("Failed to fetch market data");
      console.error(err);
    }
  };

  useEffect(() => {
    const initData = async () => {
      await fetchKlineData();
    };
    void initData();
    // Refresh every 30 seconds
    const interval = setInterval(() => {
      void initData();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  // Sort by volume spike and change
  const sortedPairs = [...pairData].sort((a, b) => {
    if (a.volumeSpike !== b.volumeSpike) return b.volumeSpike ? 1 : -1;
    return Math.abs(b.change24h) - Math.abs(a.change24h);
  });

  return (
    <div className="space-y-6">
      {/* Volume Heatmap */}
      <Card>
        <CardHeader>
          <CardTitle>Volume Heatmap (1H)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
            {sortedPairs.map((pair) => (
              <div
                key={pair.pair}
                className={`p-4 rounded-lg text-center cursor-pointer transition-all ${
                  pair.volumeSpike
                    ? "bg-red-100 border-2 border-red-500"
                    : "bg-neutral-100 border border-neutral-300"
                }`}
              >
                <p className="font-semibold text-sm">{pair.pair}</p>
                <p className="text-xs text-muted-foreground">${pair.currentPrice.toFixed(2)}</p>
                <p className={`text-sm font-bold ${pair.change24h > 0 ? "text-green-600" : "text-red-600"}`}>
                  {pair.change24h > 0 ? "+" : ""}{pair.change24h.toFixed(2)}%
                </p>
                {pair.volumeSpike && <Badge variant="outline" className="mt-2 text-xs">SPIKE</Badge>}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Top Movers */}
      <Card>
        <CardHeader>
          <CardTitle>Top Movers</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {sortedPairs.map((pair) => (
              <div key={pair.pair} className="flex items-center justify-between p-2 border-b last:border-b-0">
                <div>
                  <p className="font-semibold">{pair.pair}</p>
                  <p className="text-xs text-muted-foreground">${pair.currentPrice.toFixed(2)}</p>
                </div>
                <div className="text-right">
                  <p className={`font-bold ${pair.change24h > 0 ? "text-green-600" : "text-red-600"}`}>
                    {pair.change24h > 0 ? "+" : ""}{pair.change24h.toFixed(2)}%
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Vol: {(pair.volume24h / 1000000).toFixed(2)}M
                  </p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Token Table */}
      <Card>
        <CardHeader>
          <CardTitle>Token Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-2">Pair</th>
                  <th className="text-right py-2 px-2">Price</th>
                  <th className="text-right py-2 px-2">24h Change</th>
                  <th className="text-right py-2 px-2">Volume</th>
                  <th className="text-center py-2 px-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {sortedPairs.map((pair) => (
                  <tr key={pair.pair} className="border-b hover:bg-neutral-50">
                    <td className="py-3 px-2 font-semibold">{pair.pair}</td>
                    <td className="text-right py-3 px-2">${pair.currentPrice.toFixed(2)}</td>
                    <td className={`text-right py-3 px-2 ${pair.change24h > 0 ? "text-green-600" : "text-red-600"}`}>
                      {pair.change24h > 0 ? "+" : ""}{pair.change24h.toFixed(2)}%
                    </td>
                    <td className="text-right py-3 px-2">{(pair.volume24h / 1000000).toFixed(2)}M</td>
                    <td className="text-center py-3 px-2">
                      {pair.volumeSpike ? (
                        <Badge className="bg-red-500">Volume Spike</Badge>
                      ) : (
                        <Badge variant="outline">Normal</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {error && <div className="text-red-600 text-sm">{error}</div>}
    </div>
  );
}
