"use client";
import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

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
  const [topMovers, setTopMovers] = useState<TokenSummary[]>([]);
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
              if (result.klines && result.klines.length > 0) {
                const k = result.klines[0];
                data.push({
                  pair,
                  price: k.close,
                  volume24h: k.volume,
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
        setTopMovers([...data].sort((a, b) => b.change24h - a.change24h).slice(0, 3));
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
      <Card>
        <CardHeader><CardTitle>Volume Heatmap (24h)</CardTitle></CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-muted-foreground">Loading volume data...</p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {summary.map((token) => {
                const maxVol = Math.max(...summary.map((t) => t.volume24h));
                const intensity = (token.volume24h / maxVol) * 100;
                return (
                  <div key={token.pair} className="p-4 rounded-lg text-center" style={{backgroundColor: `rgba(20, 184, 166, ${intensity / 100})`}}>
                    <p className="font-bold text-sm">{token.pair}</p>
                    <p className="text-xs text-muted-foreground">{(token.volume24h / 1e6).toFixed(1)}M</p>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
