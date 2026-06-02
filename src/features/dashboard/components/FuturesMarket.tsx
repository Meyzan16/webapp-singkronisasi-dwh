"use client";
import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface FuturesTicker {
  symbol: string;
  price: number;
  change_24h: number;
  volume_24h: number;
  high_24h: number;
  low_24h: number;
}

interface MarketData {
  tickers: FuturesTicker[];
}

export function FuturesMarket() {
  const [data, setData] = useState<MarketData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/v1/market/futures-market");
      if (!res.ok) throw new Error(await res.text());
      setData(await res.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch market data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(() => void fetchData(), 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const tickers = data?.tickers ?? [];
  const visible = showAll ? tickers : tickers.slice(0, 20);

  const formatVolume = (v: number) => {
    if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`;
    if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
    return `$${(v / 1_000).toFixed(0)}K`;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Futures Market — 24h Change</span>
          {data && (
            <span className="text-xs text-muted-foreground font-normal">
              {tickers.length} pairs • sorted by gain ↑
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading && !data && (
          <p className="text-sm text-muted-foreground">Loading market data...</p>
        )}
        {error && <p className="text-sm text-red-500">{error}</p>}
        {data && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b">
                    <th className="text-left py-2 pr-3">#</th>
                    <th className="text-left py-2 pr-3">Symbol</th>
                    <th className="text-right py-2 pr-3">Price</th>
                    <th className="text-right py-2 pr-3">24h %</th>
                    <th className="text-right py-2 pr-3">Volume</th>
                    <th className="text-right py-2 pr-3">High</th>
                    <th className="text-right py-2">Low</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((t, i) => (
                    <tr key={t.symbol} className="border-b border-neutral-50 hover:bg-neutral-50">
                      <td className="py-2 pr-3 text-muted-foreground text-xs">{i + 1}</td>
                      <td className="py-2 pr-3 font-semibold">
                        {t.symbol.replace("USDT", "")}
                        <span className="text-xs text-muted-foreground font-normal">/USDT</span>
                      </td>
                      <td className="py-2 pr-3 text-right font-mono text-xs">
                        ${t.price < 0.001
                          ? t.price.toFixed(6)
                          : t.price < 1
                          ? t.price.toFixed(4)
                          : t.price.toLocaleString()}
                      </td>
                      <td className={`py-2 pr-3 text-right font-bold ${t.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
                        {t.change_24h >= 0 ? "+" : ""}{t.change_24h.toFixed(2)}%
                      </td>
                      <td className="py-2 pr-3 text-right text-xs text-muted-foreground">
                        {formatVolume(t.volume_24h)}
                      </td>
                      <td className="py-2 pr-3 text-right text-xs text-green-600 font-mono">
                        ${t.high_24h < 1 ? t.high_24h.toFixed(4) : t.high_24h.toLocaleString()}
                      </td>
                      <td className="py-2 text-right text-xs text-red-500 font-mono">
                        ${t.low_24h < 1 ? t.low_24h.toFixed(4) : t.low_24h.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {tickers.length > 20 && (
              <button
                onClick={() => setShowAll(!showAll)}
                className="mt-3 w-full text-xs text-primarygreen hover:underline"
              >
                {showAll ? "Show less ↑" : `Show all ${tickers.length} pairs ↓`}
              </button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
