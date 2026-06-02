"use client";
import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface FuturesPosition {
  symbol: string;
  side: string;
  size: number;
  entry_price: number;
  mark_price: number;
  unrealized_pnl: number;
  roe_percent: number;
  margin: number;
  leverage: number;
}

interface FuturesData {
  positions: FuturesPosition[];
  total_unrealized_pnl: number;
}

export function FuturesPositions() {
  const [data, setData] = useState<FuturesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/v1/market/futures-positions");
      if (!res.ok) throw new Error(await res.text());
      setData(await res.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch futures positions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(() => void fetchData(), 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Active Futures Positions</span>
          {data && data.positions.length > 0 && (
            <span className={`text-sm font-bold ${data.total_unrealized_pnl >= 0 ? "text-green-600" : "text-red-500"}`}>
              {data.total_unrealized_pnl >= 0 ? "+" : ""}${data.total_unrealized_pnl.toFixed(2)} uPnL
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading && !data && (
          <p className="text-sm text-muted-foreground">Loading futures positions...</p>
        )}
        {error && <p className="text-sm text-red-500">{error}</p>}
        {data && data.positions.length === 0 && (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <span className="text-2xl mb-2">📭</span>
            <p className="text-sm text-muted-foreground">No active futures positions</p>
            <p className="text-xs text-muted-foreground mt-1">Signals will appear here when a trade is opened</p>
          </div>
        )}
        {data && data.positions.length > 0 && (
          <div className="space-y-3">
            {data.positions.map((p) => (
              <div key={p.symbol} className={`p-3 rounded-lg border ${p.unrealized_pnl >= 0 ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200"}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Badge className={p.side === "LONG" ? "bg-green-500" : "bg-red-500"}>
                      {p.side} {p.leverage}x
                    </Badge>
                    <span className="font-bold text-sm">{p.symbol}</span>
                  </div>
                  <div className="text-right">
                    <p className={`font-bold text-sm ${p.unrealized_pnl >= 0 ? "text-green-600" : "text-red-500"}`}>
                      {p.unrealized_pnl >= 0 ? "+" : ""}${p.unrealized_pnl.toFixed(4)}
                    </p>
                    <p className={`text-xs ${p.roe_percent >= 0 ? "text-green-500" : "text-red-400"}`}>
                      ROE: {p.roe_percent >= 0 ? "+" : ""}{p.roe_percent.toFixed(2)}%
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                  <div>
                    <p>Entry</p>
                    <p className="font-mono text-foreground">${p.entry_price.toLocaleString()}</p>
                  </div>
                  <div>
                    <p>Mark</p>
                    <p className="font-mono text-foreground">${p.mark_price.toLocaleString()}</p>
                  </div>
                  <div>
                    <p>Margin</p>
                    <p className="font-mono text-foreground">${p.margin.toFixed(2)}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
