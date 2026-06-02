"use client";
import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface SpotAsset {
  asset: string;
  free: number;
  locked: number;
  total: number;
  usdt_value: number;
}

interface SpotData {
  assets: SpotAsset[];
  total_usdt_value: number;
}

export function SpotPositions() {
  const [data, setData] = useState<SpotData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/v1/market/spot-positions");
      if (!res.ok) throw new Error(await res.text());
      setData(await res.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch spot positions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(() => void fetchData(), 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Spot Portfolio</span>
          {data && (
            <span className="text-lg font-bold text-primarygreen">
              ${data.total_usdt_value.toLocaleString()}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading && !data && (
          <p className="text-sm text-muted-foreground">Loading positions...</p>
        )}
        {error && (
          <p className="text-sm text-red-500">{error}</p>
        )}
        {data && data.assets.length === 0 && (
          <p className="text-sm text-muted-foreground">No spot holdings found.</p>
        )}
        {data && data.assets.length > 0 && (
          <div className="space-y-2">
            {data.assets.map((a) => {
              const pct = (a.usdt_value / data.total_usdt_value) * 100;
              return (
                <div key={a.asset} className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-primarygreen/10 flex items-center justify-center flex-shrink-0">
                    <span className="text-xs font-bold text-primarygreen">
                      {a.asset.slice(0, 3)}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-center mb-1">
                      <span className="font-semibold text-sm">{a.asset}</span>
                      <span className="text-sm font-bold">${a.usdt_value.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-xs text-muted-foreground">{a.total.toFixed(6)}</span>
                      <span className="text-xs text-muted-foreground">{pct.toFixed(1)}%</span>
                    </div>
                    <div className="w-full bg-neutral-100 rounded-full h-1.5">
                      <div
                        className="bg-primarygreen h-full rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                  {a.locked > 0 && (
                    <Badge variant="outline" className="text-xs flex-shrink-0">
                      🔒 {a.locked.toFixed(4)}
                    </Badge>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
