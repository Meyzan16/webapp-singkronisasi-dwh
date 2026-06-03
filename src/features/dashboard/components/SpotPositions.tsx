"use client";
import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface SpotAsset {
  asset: string;
  free: number;
  locked: number;
  total: number;
  current_price: number;
  usdt_value: number;
  avg_buy_price: number | null;
  pnl_usdt: number | null;
  pnl_percent: number | null;
}

interface SpotData {
  assets: SpotAsset[];
  total_usdt_value: number;
  total_pnl_usdt: number;
}

const fmtPrice = (p: number) =>
  p < 0.0001 ? p.toFixed(8) : p < 1 ? p.toFixed(6) : p < 1000 ? p.toFixed(4) : p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtUsd = (v: number) =>
  Math.abs(v) >= 1000 ? `$${(v / 1000).toFixed(2)}K` : `$${v.toFixed(2)}`;

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
      setError(e instanceof Error ? e.message : "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(() => void fetchData(), 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const totalPnl = data?.total_pnl_usdt ?? 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between gap-2 flex-wrap">
          <span>📦 Spot Portfolio</span>
          {data && (
            <div className="text-right">
              <p className="text-lg font-bold text-primarygreen leading-tight">
                {fmtUsd(data.total_usdt_value)}
              </p>
              {totalPnl !== 0 && (
                <p className={`text-xs font-semibold ${totalPnl >= 0 ? "text-green-600" : "text-red-500"}`}>
                  {totalPnl >= 0 ? "▲" : "▼"} {fmtUsd(Math.abs(totalPnl))} P&L
                </p>
              )}
            </div>
          )}
        </CardTitle>
      </CardHeader>

      <CardContent className="pt-0">
        {loading && !data && (
          <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <span className="animate-spin w-4 h-4 border-2 border-primarygreen border-t-transparent rounded-full" />
            Loading positions...
          </div>
        )}
        {error && (
          <div className="text-sm text-red-500 bg-red-50 rounded-lg px-3 py-2">{error}</div>
        )}
        {data && data.assets.length === 0 && (
          <p className="text-sm text-muted-foreground py-4">No spot holdings found.</p>
        )}

        {data && data.assets.length > 0 && (
          <div className="space-y-1">
            {/* Header row */}
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 text-[10px] text-muted-foreground uppercase tracking-wide px-1 pb-1 border-b">
              <span>Asset</span>
              <span className="text-right">Avg Buy</span>
              <span className="text-right">Now</span>
              <span className="text-right">P&L</span>
            </div>

            {data.assets.map((a) => {
              const pct = (a.usdt_value / data.total_usdt_value) * 100;
              const hasPnl = a.pnl_percent !== null && a.avg_buy_price !== null;
              const isProfit = (a.pnl_percent ?? 0) >= 0;

              return (
                <div key={a.asset} className="py-2 border-b border-neutral-50 last:border-0">
                  <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 items-center">
                    {/* Asset info */}
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="w-8 h-8 rounded-full bg-primarygreen/10 flex items-center justify-center flex-shrink-0">
                        <span className="text-[10px] font-bold text-primarygreen">{a.asset.slice(0, 3)}</span>
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1">
                          <span className="font-semibold text-sm">{a.asset}</span>
                          {a.locked > 0 && <Badge variant="outline" className="text-[9px] px-1 py-0">🔒</Badge>}
                        </div>
                        <span className="text-[10px] text-muted-foreground">
                          {a.total < 0.0001 ? a.total.toFixed(8) : a.total.toFixed(4)} · {fmtUsd(a.usdt_value)} ({pct.toFixed(1)}%)
                        </span>
                      </div>
                    </div>

                    {/* Avg buy price */}
                    <div className="text-right">
                      {a.avg_buy_price ? (
                        <span className="text-xs font-mono text-neutral-600">
                          ${fmtPrice(a.avg_buy_price)}
                        </span>
                      ) : (
                        <span className="text-[10px] text-neutral-300">—</span>
                      )}
                    </div>

                    {/* Current price */}
                    <div className="text-right">
                      {a.asset !== "USDT" ? (
                        <span className="text-xs font-mono font-semibold">
                          ${fmtPrice(a.current_price)}
                        </span>
                      ) : (
                        <span className="text-xs font-mono text-muted-foreground">$1.00</span>
                      )}
                    </div>

                    {/* P&L */}
                    <div className="text-right min-w-[52px]">
                      {hasPnl ? (
                        <div>
                          <p className={`text-xs font-bold ${isProfit ? "text-green-600" : "text-red-500"}`}>
                            {isProfit ? "+" : ""}{a.pnl_percent?.toFixed(2)}%
                          </p>
                          <p className={`text-[10px] ${isProfit ? "text-green-500" : "text-red-400"}`}>
                            {isProfit ? "+" : ""}{fmtUsd(a.pnl_usdt!)}
                          </p>
                        </div>
                      ) : (
                        <span className="text-[10px] text-neutral-300">—</span>
                      )}
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="mt-1.5 w-full bg-neutral-100 rounded-full h-1">
                    <div className="bg-primarygreen h-full rounded-full transition-all" style={{ width: `${Math.min(pct, 100)}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
