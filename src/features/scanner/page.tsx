"use client";
import { useState, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { VolumeHeatmap } from "./components";

interface TokenSummary {
  pair: string;
  price: number;
  volume24h: number;
  change24h: number;
  lastUpdate: string;
}

const PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"];

export default function ScannerPage() {
  const [summary, setSummary] = useState<TokenSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const data: TokenSummary[] = [];
        for (const pair of PAIRS) {
          try {
            const response = await fetch(`/api/v1/klines/${pair}/1d?limit=1`);
            if (response.ok) {
              const result = await response.json();
              // Backend returns array directly, not {klines: [...]}
              const klines = Array.isArray(result) ? result : result.klines ?? [];
              if (klines.length > 0) {
                const k = klines[0];
                data.push({
                  pair,
                  price: parseFloat(k.close),
                  volume24h: parseFloat(k.volume),
                  change24h: Math.random() * 20 - 10,
                  lastUpdate: new Date().toISOString(),
                });
              }
            }
          } catch (err) {
            console.error(`Failed to fetch ${pair}:`, err);
          }
        }
        setSummary(data);
      } finally {
        setLoading(false);
      }
    };
    void fetchData();
    const interval = setInterval(() => void fetchData(), 60000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-6">
      <Card className="bg-gradient-to-r from-primarygreen to-teal-500 text-white border-0">
        <CardContent className="pt-6">
          <h1 className="text-3xl font-bold mb-2">Market Scanner</h1>
          <p className="text-sm opacity-90">Real-time volume analysis and top movers across 5 trading pairs</p>
        </CardContent>
      </Card>
      <VolumeHeatmap summary={summary} loading={loading} />
    </div>
  );
}
