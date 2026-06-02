"use client";
import { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { CandlestickChart } from "./CandlestickChart";

interface Candle {
  time: number; open: number; high: number; low: number; close: number; volume: number;
}
interface CoinInfo {
  symbol: string; last_price: number; mark_price: number; index_price: number;
  change_24h: number; high_24h: number; low_24h: number; volume_24h: number;
  quote_volume_24h: number; open_interest: number; funding_rate: number;
  next_funding_time: number; count_24h: number;
}
interface TALayer { name: string; status: string; signal?: string; detail?: string; }
interface Analysis {
  direction: string | null; entry: number | null; stop_loss: number | null;
  take_profit: number | null; risk_reward: string | null; confidence: number | null;
  skip_reason: string | null; layers: TALayer[];
}

const INTERVALS = ["15m", "1h", "4h", "1d"] as const;
type Interval = typeof INTERVALS[number];

interface CoinModalProps {
  symbol: string;
  onClose: () => void;
}

export function CoinModal({ symbol, onClose }: CoinModalProps) {
  const [tab, setTab] = useState<"chart" | "info" | "analysis">("chart");
  const [interval, setInterval] = useState<Interval>("1h");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [info, setInfo] = useState<CoinInfo | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [loadingCandles, setLoadingCandles] = useState(true);

  const base = symbol.replace("USDT", "");

  const fetchCandles = useCallback(async (iv: Interval) => {
    setLoadingCandles(true);
    try {
      const r = await fetch(`/api/v1/coin/${symbol}/klines?interval=${iv}&limit=200`);
      const d = await r.json();
      setCandles(d.candles ?? []);
    } finally {
      setLoadingCandles(false);
    }
  }, [symbol]);

  const fetchInfo = useCallback(async () => {
    const r = await fetch(`/api/v1/coin/${symbol}/info`);
    setInfo(await r.json());
  }, [symbol]);

  const runAnalysis = async (iv: Interval) => {
    setAnalyzing(true);
    setAnalysis(null);
    try {
      const r = await fetch(`/api/v1/coin/${symbol}/analyze?interval=${iv}&limit=200`);
      setAnalysis(await r.json());
    } finally {
      setAnalyzing(false);
    }
  };

  useEffect(() => {
    void fetchCandles(interval);
    void fetchInfo();
  }, [symbol, interval, fetchCandles, fetchInfo]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const fmtPrice = (p: number) =>
    p < 0.001 ? p.toFixed(6) : p < 1 ? p.toFixed(4) : p.toLocaleString(undefined, { minimumFractionDigits: 2 });
  const fmtVol = (v: number) =>
    v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${(v / 1e3).toFixed(0)}K`;

  const layerColor = (status: string) =>
    status === "passed" ? "bg-green-100 text-green-800 border-green-300"
    : status === "failed" ? "bg-red-100 text-red-800 border-red-300"
    : "bg-neutral-100 text-neutral-600 border-neutral-200";

  const layerIcon = (status: string) =>
    status === "passed" ? "✓" : status === "failed" ? "✗" : "~";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b bg-gradient-to-r from-primarygreen to-teal-500 text-white">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-white/20 flex items-center justify-center font-bold text-sm">
              {base.slice(0, 3)}
            </div>
            <div>
              <h2 className="text-xl font-bold">{base}/USDT</h2>
              <p className="text-xs opacity-80">Binance Futures Perpetual</p>
            </div>
          </div>
          {info && (
            <div className="text-right">
              <p className="text-2xl font-bold">${fmtPrice(info.last_price)}</p>
              <p className={`text-sm font-semibold ${info.change_24h >= 0 ? "text-green-200" : "text-red-200"}`}>
                {info.change_24h >= 0 ? "▲" : "▼"} {Math.abs(info.change_24h).toFixed(2)}%
              </p>
            </div>
          )}
          <button onClick={onClose} className="ml-4 w-8 h-8 rounded-full bg-white/20 hover:bg-white/30 flex items-center justify-center text-white font-bold text-lg">
            ×
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b px-6 bg-neutral-50">
          {(["chart", "info", "analysis"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-3 text-sm font-semibold capitalize border-b-2 transition-colors ${
                tab === t ? "border-primarygreen text-primarygreen" : "border-transparent text-muted-foreground hover:text-black"
              }`}
            >
              {t === "chart" ? "📈 Chart" : t === "info" ? "📊 Market Info" : "🤖 TA Analysis"}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">

          {/* ─── CHART TAB ─── */}
          {tab === "chart" && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                {INTERVALS.map((iv) => (
                  <button
                    key={iv}
                    onClick={() => { setInterval(iv); void fetchCandles(iv); }}
                    className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
                      interval === iv ? "bg-primarygreen text-white" : "bg-neutral-100 hover:bg-neutral-200"
                    }`}
                  >
                    {iv.toUpperCase()}
                  </button>
                ))}
                {loadingCandles && <span className="text-xs text-muted-foreground animate-pulse">Loading...</span>}
              </div>
              {candles.length > 0 && !loadingCandles && (
                <CandlestickChart candles={candles} height={360} />
              )}
            </div>
          )}

          {/* ─── INFO TAB ─── */}
          {tab === "info" && info && (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {[
                { label: "Last Price", value: `$${fmtPrice(info.last_price)}` },
                { label: "Mark Price", value: `$${fmtPrice(info.mark_price)}` },
                { label: "Index Price", value: `$${fmtPrice(info.index_price)}` },
                { label: "24h Change", value: `${info.change_24h >= 0 ? "+" : ""}${info.change_24h.toFixed(2)}%`, color: info.change_24h >= 0 ? "text-green-600" : "text-red-500" },
                { label: "24h High", value: `$${fmtPrice(info.high_24h)}`, color: "text-green-600" },
                { label: "24h Low", value: `$${fmtPrice(info.low_24h)}`, color: "text-red-500" },
                { label: "Volume (coin)", value: info.volume_24h.toLocaleString() },
                { label: "Volume (USDT)", value: fmtVol(info.quote_volume_24h) },
                { label: "Open Interest", value: info.open_interest.toLocaleString() },
                { label: "Funding Rate", value: `${info.funding_rate}%`, color: info.funding_rate >= 0 ? "text-green-600" : "text-red-500" },
                { label: "Trades (24h)", value: info.count_24h.toLocaleString() },
                { label: "Next Funding", value: info.next_funding_time ? new Date(info.next_funding_time).toLocaleTimeString() : "—" },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-neutral-50 rounded-xl p-4 border">
                  <p className="text-xs text-muted-foreground mb-1">{label}</p>
                  <p className={`text-lg font-bold ${color ?? ""}`}>{value}</p>
                </div>
              ))}
            </div>
          )}

          {/* ─── ANALYSIS TAB ─── */}
          {tab === "analysis" && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-muted-foreground">Timeframe:</span>
                {INTERVALS.map((iv) => (
                  <button key={iv} onClick={() => setInterval(iv)}
                    className={`px-3 py-1 rounded-lg text-sm font-medium ${interval === iv ? "bg-primarygreen text-white" : "bg-neutral-100"}`}>
                    {iv.toUpperCase()}
                  </button>
                ))}
                <button
                  onClick={() => void runAnalysis(interval)}
                  disabled={analyzing}
                  className="ml-auto px-5 py-2 bg-primarygreen text-white rounded-lg font-semibold text-sm hover:bg-teal-600 disabled:opacity-50 flex items-center gap-2"
                >
                  {analyzing
                    ? <><span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" /> Running...</>
                    : "▶ Run Backtest (T0→T4)"}
                </button>
              </div>

              {!analysis && !analyzing && (
                <div className="text-center py-12 text-muted-foreground">
                  <p className="text-4xl mb-3">🤖</p>
                  <p className="font-semibold">Click &quot;Run Backtest&quot; to analyze {base}/USDT</p>
                  <p className="text-sm mt-1">Runs T0 Wyckoff &#8594; T1 Trend &#8594; T2 S/R &#8594; T3 Pattern &#8594; T4 Trigger</p>
                </div>
              )}

              {analysis && (
                <div className="space-y-4">
                  {/* Signal Result */}
                  <div className={`p-5 rounded-2xl border-2 text-center ${
                    analysis.direction === "LONG" ? "bg-green-50 border-green-400"
                    : analysis.direction === "SHORT" ? "bg-red-50 border-red-400"
                    : "bg-neutral-50 border-neutral-300"
                  }`}>
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Signal Result</p>
                    {analysis.direction ? (
                      <>
                        <p className={`text-4xl font-black mb-2 ${analysis.direction === "LONG" ? "text-green-600" : "text-red-500"}`}>
                          {analysis.direction === "LONG" ? "🟢 BUY" : "🔴 SELL"}
                        </p>
                        <p className="text-sm text-muted-foreground mb-3">Confidence: <strong>{analysis.confidence?.toFixed(0)}%</strong></p>
                        <div className="grid grid-cols-3 gap-4 text-left">
                          <div className="bg-white rounded-lg p-3 border">
                            <p className="text-xs text-muted-foreground">Entry</p>
                            <p className="font-bold text-base">${fmtPrice(analysis.entry!)}</p>
                          </div>
                          <div className="bg-white rounded-lg p-3 border border-red-200">
                            <p className="text-xs text-red-500">Stop Loss</p>
                            <p className="font-bold text-base text-red-600">${fmtPrice(analysis.stop_loss!)}</p>
                          </div>
                          <div className="bg-white rounded-lg p-3 border border-green-200">
                            <p className="text-xs text-green-600">Take Profit</p>
                            <p className="font-bold text-base text-green-600">${fmtPrice(analysis.take_profit!)}</p>
                          </div>
                        </div>
                        <p className="text-sm mt-3 text-muted-foreground">Risk:Reward = <strong className="text-primarygreen">{analysis.risk_reward}</strong></p>
                      </>
                    ) : (
                      <>
                        <p className="text-3xl font-black text-neutral-500 mb-2">⏸ NO SIGNAL</p>
                        <p className="text-sm text-muted-foreground">{analysis.skip_reason}</p>
                      </>
                    )}
                  </div>

                  {/* Layer Breakdown */}
                  <div>
                    <p className="text-sm font-semibold mb-3 text-muted-foreground">Pipeline Breakdown</p>
                    <div className="space-y-2">
                      {analysis.layers.map((layer, i) => (
                        <div key={i} className={`p-3 rounded-xl border flex items-start gap-3 ${layerColor(layer.status)}`}>
                          <span className="text-lg font-bold flex-shrink-0 w-6 text-center">{layerIcon(layer.status)}</span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-semibold text-sm">{layer.name}</span>
                              {layer.signal && (
                                <Badge variant="outline" className="text-xs">{layer.signal}</Badge>
                              )}
                            </div>
                            {layer.detail && (
                              <p className="text-xs mt-0.5 opacity-80">{layer.detail}</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
