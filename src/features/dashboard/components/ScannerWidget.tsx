"use client";
import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface ScannerResult {
  symbol: string;
  direction: string;
  score: number;
  change_24h: number;
  volume_ratio: number;
  momentum: string;
  trigger: string;
  entry: number;
  stop_loss: number;
  take_profit: number;
  risk_reward: string;
}

interface ScannerData {
  results: ScannerResult[];
  scanned: number;
  generated_at: number;
}

const MOMENTUM_COLORS: Record<string, string> = {
  strong_up: "text-green-500 font-bold",
  up: "text-green-400",
  neutral: "text-neutral-400",
  down: "text-red-400",
  strong_down: "text-red-500 font-bold",
};

const MOMENTUM_LABELS: Record<string, string> = {
  strong_up: "🚀 Strong Up", up: "↑ Up",
  neutral: "→ Neutral", down: "↓ Down", strong_down: "💥 Strong Down",
};

const fmtPrice = (p: number) =>
  p < 0.001 ? p.toFixed(6) : p < 1 ? p.toFixed(4) : p.toLocaleString(undefined, { maximumFractionDigits: 2 });

interface ScannerWidgetProps { fullPage?: boolean; }

export function ScannerWidget({ fullPage = false }: ScannerWidgetProps) {
  const [data, setData] = useState<ScannerData | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"ALL" | "LONG" | "SHORT">("ALL");

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const r = await fetch("/api/v1/scanner/scan");
      setData(await r.json());
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void fetchData();
    const t = setInterval(() => void fetchData(), 5 * 60 * 1000);
    return () => clearInterval(t);
  }, [fetchData]);

  const filtered = data?.results.filter(r => filter === "ALL" || r.direction === filter) ?? [];
  const timeAgo = data ? Math.floor((Date.now() / 1000 - data.generated_at) / 60) : 0;

  return (
    <Card className="border-0 bg-gradient-to-b from-neutral-950 to-neutral-900 text-white">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <span className="text-lg">🤖</span>
            <span className="text-base font-bold">24H Scanner Agent</span>
            {loading && <span className="animate-spin w-3 h-3 border-2 border-primarygreen border-t-transparent rounded-full" />}
          </div>
          <div className="flex items-center gap-2">
            {data && (
              <span className="text-xs text-neutral-500">
                {data.scanned} scanned · {timeAgo === 0 ? "just now" : `${timeAgo}m ago`}
              </span>
            )}
            <button onClick={() => void fetchData()}
              className="text-xs bg-neutral-800 hover:bg-neutral-700 px-2 py-1 rounded-lg transition-colors">
              ↻ Refresh
            </button>
          </div>
        </CardTitle>

        {/* Filter */}
        <div className="flex gap-1">
          {(["ALL", "LONG", "SHORT"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                filter === f
                  ? f === "LONG" ? "bg-green-600 text-white" : f === "SHORT" ? "bg-red-600 text-white" : "bg-primarygreen text-white"
                  : "bg-neutral-800 text-neutral-400 hover:text-white"
              }`}>
              {f} {f !== "ALL" && data ? `(${data.results.filter(r => r.direction === f).length})` : ""}
            </button>
          ))}
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        {loading && !data && (
          <div className="py-8 text-center text-neutral-500 text-sm">
            <p className="animate-pulse">Scanning 598 pairs...</p>
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <p className="text-center text-neutral-500 text-sm py-6">No setups found for current filter</p>
        )}

        {filtered.length > 0 && (
          <div className={fullPage ? "grid grid-cols-1 md:grid-cols-2 gap-2" : "space-y-2"}>
            {filtered.map((r) => {
              const base = r.symbol.replace("USDT", "");
              const isLong = r.direction === "LONG";
              const scoreColor = r.score >= 75 ? "text-green-400" : r.score >= 55 ? "text-yellow-400" : "text-neutral-400";

              return (
                <div key={r.symbol}
                  className={`rounded-xl p-3 border transition-all hover:border-primarygreen/50 cursor-pointer ${
                    isLong ? "bg-green-950/30 border-green-900/50" : "bg-red-950/30 border-red-900/50"
                  }`}>
                  <div className="flex items-center justify-between gap-2">
                    {/* Symbol + direction */}
                    <div className="flex items-center gap-2 min-w-0">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-black flex-shrink-0 ${
                        isLong ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                      }`}>
                        {base.slice(0, 3)}
                      </div>
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold text-sm text-white">{base}</span>
                          <Badge className={`text-[10px] px-1.5 py-0 font-bold ${
                            isLong ? "bg-green-600 text-white" : "bg-red-600 text-white"
                          }`}>
                            {isLong ? "▲ LONG" : "▼ SHORT"}
                          </Badge>
                          <span className={`text-[10px] font-bold ${r.change_24h >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {r.change_24h >= 0 ? "+" : ""}{r.change_24h}%
                          </span>
                        </div>
                        <p className="text-[10px] text-neutral-500 truncate max-w-[180px]">{r.trigger}</p>
                      </div>
                    </div>

                    {/* Score + price */}
                    <div className="text-right flex-shrink-0">
                      <div className="flex items-center gap-1 justify-end">
                        <span className={`text-base font-black ${scoreColor}`}>{r.score}</span>
                        <span className="text-[10px] text-neutral-500">pts</span>
                      </div>
                      <p className="text-xs font-mono text-neutral-300">${fmtPrice(r.entry)}</p>
                    </div>
                  </div>

                  {/* Details row */}
                  <div className="mt-2 flex items-center justify-between text-[10px] text-neutral-400">
                    <div className="flex gap-3">
                      <span>Vol <strong className="text-neutral-300">{r.volume_ratio}x</strong></span>
                      <span className={MOMENTUM_COLORS[r.momentum] ?? "text-neutral-400"}>
                        {MOMENTUM_LABELS[r.momentum] ?? r.momentum}
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <span>SL <strong className="text-red-400">${fmtPrice(r.stop_loss)}</strong></span>
                      <span>TP <strong className="text-green-400">${fmtPrice(r.take_profit)}</strong></span>
                      <span className="text-primarygreen font-bold">{r.risk_reward}</span>
                    </div>
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
