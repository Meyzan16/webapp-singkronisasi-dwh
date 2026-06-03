"use client";
import { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { CandlestickChart } from "./CandlestickChart";

interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number; }
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

const PIPELINE_STEPS = [
  { key: "T0 Wyckoff",   icon: "🌀", label: "T0", desc: "Wyckoff Phase",      color: "purple"  },
  { key: "T1 Trend",     icon: "📈", label: "T1", desc: "EMA Trend",          color: "blue"    },
  { key: "T2 S/R Zones", icon: "🏔", label: "T2", desc: "Support/Resistance", color: "orange"  },
  { key: "T3 Pattern",   icon: "🔷", label: "T3", desc: "Chart Pattern",      color: "teal"    },
  { key: "T4 Trigger",   icon: "⚡", label: "T4", desc: "Entry Trigger",      color: "green"   },
];

type PipelineStatus = "idle" | "running" | "done" | "error";

interface CoinModalProps { symbol: string; onClose: () => void; }

export function CoinModal({ symbol, onClose }: CoinModalProps) {
  const [tab, setTab] = useState<"chart" | "info" | "analysis">("chart");
  const [interval, setInterval] = useState<Interval>("1h");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [info, setInfo] = useState<CoinInfo | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus>("idle");
  const [visibleLayers, setVisibleLayers] = useState<number>(0);
  const [loadingCandles, setLoadingCandles] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const base = symbol.replace("USDT", "");

  const fetchCandles = useCallback(async (iv: Interval) => {
    setLoadingCandles(true);
    try {
      const r = await fetch(`/api/v1/coin/${symbol}/klines?interval=${iv}&limit=200`);
      const d = await r.json();
      setCandles(d.candles ?? []);
    } catch { /* silent */ }
    finally { setLoadingCandles(false); }
  }, [symbol]);

  const fetchInfo = useCallback(async () => {
    try {
      const r = await fetch(`/api/v1/coin/${symbol}/info`);
      setInfo(await r.json());
    } catch { /* silent */ }
  }, [symbol]);

  useEffect(() => { void fetchCandles(interval); void fetchInfo(); }, [symbol, interval, fetchCandles, fetchInfo]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const runAnalysis = async (iv: Interval) => {
    setPipelineStatus("running");
    setAnalysis(null);
    setVisibleLayers(0);
    setError(null);

    try {
      const r = await fetch(`/api/v1/coin/${symbol}/analyze?interval=${iv}&limit=200`);
      const data: Analysis & { detail?: string } = await r.json();

      if (!r.ok || data.detail) {
        setError(data.detail ?? "Analysis failed");
        setPipelineStatus("error");
        return;
      }

      // Animate pipeline layers one by one
      const layers = data.layers ?? [];
      for (let i = 0; i < layers.length; i++) {
        await new Promise(res => setTimeout(res, 600));
        setVisibleLayers(i + 1);
      }

      await new Promise(res => setTimeout(res, 400));
      setAnalysis(data);
      setPipelineStatus("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
      setPipelineStatus("error");
    }
  };

  const fmtPrice = (p: number) =>
    p < 0.001 ? p.toFixed(6) : p < 1 ? p.toFixed(4) : p.toLocaleString(undefined, { minimumFractionDigits: 2 });
  const fmtVol = (v: number) =>
    v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${(v / 1e3).toFixed(0)}K`;

  const layerBg = (status: string) =>
    status === "passed" ? "bg-green-50 border-green-300 text-green-800"
    : status === "failed" ? "bg-red-50 border-red-300 text-red-800"
    : "bg-neutral-50 border-neutral-200 text-neutral-600";

  const layerIcon = (status: string) =>
    status === "passed" ? "✓" : status === "failed" ? "✗" : "~";

  // Match pipeline step to layer data
  const getLayerData = (key: string) =>
    analysis?.layers?.find(l => l.name.startsWith(key.split(" ")[0] + " ") || l.name === key);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[92vh] flex flex-col overflow-hidden">

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 py-4 border-b bg-gradient-to-r from-primarygreen to-teal-500 text-white flex-shrink-0">
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
          <button onClick={onClose} className="ml-4 w-8 h-8 rounded-full bg-white/20 hover:bg-white/30 flex items-center justify-center text-white font-bold text-lg">×</button>
        </div>

        {/* ── Tabs ── */}
        <div className="flex border-b px-6 bg-neutral-50 flex-shrink-0">
          {(["chart", "info", "analysis"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-3 text-sm font-semibold capitalize border-b-2 transition-colors ${tab === t ? "border-primarygreen text-primarygreen" : "border-transparent text-muted-foreground hover:text-black"}`}>
              {t === "chart" ? "📈 Chart" : t === "info" ? "📊 Market Info" : "🤖 TA Analysis"}
            </button>
          ))}
        </div>

        {/* ── Content ── */}
        <div className="flex-1 overflow-y-auto p-6">

          {/* CHART */}
          {tab === "chart" && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                {INTERVALS.map((iv) => (
                  <button key={iv} onClick={() => { setInterval(iv); void fetchCandles(iv); }}
                    className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${interval === iv ? "bg-primarygreen text-white" : "bg-neutral-100 hover:bg-neutral-200"}`}>
                    {iv.toUpperCase()}
                  </button>
                ))}
                {loadingCandles && <span className="text-xs text-muted-foreground animate-pulse ml-2">Loading...</span>}
              </div>
              {candles.length > 0 && !loadingCandles && <CandlestickChart candles={candles} height={360} />}
            </div>
          )}

          {/* MARKET INFO */}
          {tab === "info" && info && (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {[
                { label: "Last Price",    value: `$${fmtPrice(info.last_price)}` },
                { label: "Mark Price",    value: `$${fmtPrice(info.mark_price)}` },
                { label: "Index Price",   value: `$${fmtPrice(info.index_price)}` },
                { label: "24h Change",    value: `${info.change_24h >= 0 ? "+" : ""}${info.change_24h.toFixed(2)}%`, color: info.change_24h >= 0 ? "text-green-600" : "text-red-500" },
                { label: "24h High",      value: `$${fmtPrice(info.high_24h)}`, color: "text-green-600" },
                { label: "24h Low",       value: `$${fmtPrice(info.low_24h)}`, color: "text-red-500" },
                { label: "Volume (coin)", value: info.volume_24h.toLocaleString() },
                { label: "Volume (USDT)", value: fmtVol(info.quote_volume_24h) },
                { label: "Open Interest", value: info.open_interest.toLocaleString() },
                { label: "Funding Rate",  value: `${info.funding_rate}%`, color: info.funding_rate >= 0 ? "text-green-600" : "text-red-500" },
                { label: "Trades (24h)",  value: info.count_24h.toLocaleString() },
                { label: "Next Funding",  value: info.next_funding_time ? new Date(info.next_funding_time).toLocaleTimeString() : "—" },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-neutral-50 rounded-xl p-4 border">
                  <p className="text-xs text-muted-foreground mb-1">{label}</p>
                  <p className={`text-lg font-bold ${color ?? ""}`}>{value}</p>
                </div>
              ))}
            </div>
          )}

          {/* TA ANALYSIS */}
          {tab === "analysis" && (
            <div className="space-y-5">

              {/* Controls */}
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-sm font-semibold text-muted-foreground">Timeframe:</span>
                {INTERVALS.map((iv) => (
                  <button key={iv} onClick={() => setInterval(iv)}
                    className={`px-3 py-1 rounded-lg text-sm font-medium ${interval === iv ? "bg-primarygreen text-white" : "bg-neutral-100"}`}>
                    {iv.toUpperCase()}
                  </button>
                ))}
                <button
                  onClick={() => void runAnalysis(interval)}
                  disabled={pipelineStatus === "running"}
                  className="ml-auto px-5 py-2 bg-primarygreen text-white rounded-lg font-semibold text-sm hover:bg-teal-600 disabled:opacity-50 flex items-center gap-2"
                >
                  {pipelineStatus === "running"
                    ? <><span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />Analyzing...</>
                    : "▶ Run Analysis (T0→T4)"}
                </button>
              </div>

              {/* IDLE state */}
              {pipelineStatus === "idle" && (
                <div className="text-center py-10 text-muted-foreground">
                  <p className="text-5xl mb-3">🤖</p>
                  <p className="font-semibold text-base">Click &quot;Run Analysis&quot; to analyze {base}/USDT</p>
                  <p className="text-sm mt-2 opacity-70">T0 Wyckoff &#8594; T1 Trend &#8594; T2 S/R &#8594; T3 Pattern &#8594; T4 Trigger</p>
                </div>
              )}

              {/* ERROR */}
              {pipelineStatus === "error" && error && (
                <div className="bg-red-50 border border-red-300 rounded-xl p-4 text-red-800 text-sm">
                  <strong>Error:</strong> {error}
                </div>
              )}

              {/* PIPELINE ANIMATION */}
              {(pipelineStatus === "running" || pipelineStatus === "done") && (
                <div className="space-y-3">
                  <p className="text-sm font-semibold text-muted-foreground">Pipeline Progress</p>

                  {/* Step-by-step pipeline */}
                  <div className="flex items-center gap-1 mb-4 overflow-x-auto pb-2">
                    {PIPELINE_STEPS.map((step, i) => {
                      const layerData = getLayerData(step.key);
                      const isVisible = i < visibleLayers;
                      const isCurrent = i === visibleLayers && pipelineStatus === "running";
                      const status = layerData?.status ?? (isCurrent ? "running" : "idle");

                      return (
                        <div key={step.key} className="flex items-center gap-1 flex-shrink-0">
                          {/* Step bubble */}
                          <div className={`flex flex-col items-center transition-all duration-500 ${isVisible ? "opacity-100 scale-100" : "opacity-30 scale-95"}`}>
                            <div className={`w-12 h-12 rounded-full flex items-center justify-center text-xl border-2 transition-all duration-300 ${
                              isCurrent ? "border-primarygreen bg-primarygreen/10 animate-pulse"
                              : status === "passed" ? "border-green-500 bg-green-50"
                              : status === "failed" ? "border-red-400 bg-red-50"
                              : status === "skipped" ? "border-neutral-300 bg-neutral-50"
                              : "border-neutral-200 bg-white"
                            }`}>
                              {isCurrent
                                ? <span className="animate-spin text-primarygreen text-base">⟳</span>
                                : status === "passed" ? <span className="text-green-600">✓</span>
                                : status === "failed" ? <span className="text-red-500">✗</span>
                                : <span>{step.icon}</span>}
                            </div>
                            <p className="text-xs font-bold mt-1">{step.label}</p>
                            <p className="text-[10px] text-muted-foreground text-center w-16 leading-tight">{step.desc}</p>
                          </div>

                          {/* Arrow between steps */}
                          {i < PIPELINE_STEPS.length - 1 && (
                            <div className={`w-6 h-0.5 flex-shrink-0 mt-[-16px] transition-all duration-300 ${isVisible && i + 1 < visibleLayers ? "bg-primarygreen" : "bg-neutral-200"}`} />
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Layer detail cards — reveal one by one */}
                  <div className="space-y-2">
                    {PIPELINE_STEPS.map((step, i) => {
                      const layer = getLayerData(step.key);
                      if (i >= visibleLayers || !layer) return null;
                      return (
                        <div key={step.key}
                          className={`p-3 rounded-xl border flex items-start gap-3 transition-all duration-300 animate-in fade-in slide-in-from-top-2 ${layerBg(layer.status)}`}>
                          <span className="text-lg font-bold w-6 text-center flex-shrink-0">{layerIcon(layer.status)}</span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-semibold text-sm">{layer.name}</span>
                              {layer.signal && layer.signal !== "No chart pattern" && (
                                <Badge variant="outline" className="text-xs">{layer.signal}</Badge>
                              )}
                            </div>
                            {layer.detail && <p className="text-xs mt-0.5 opacity-80">{layer.detail}</p>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* FINAL RESULT */}
              {pipelineStatus === "done" && analysis && (
                <div className={`p-5 rounded-2xl border-2 text-center mt-4 transition-all duration-500 ${
                  analysis.direction === "LONG" ? "bg-green-50 border-green-400"
                  : analysis.direction === "SHORT" ? "bg-red-50 border-red-400"
                  : "bg-neutral-50 border-neutral-300"
                }`}>
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">Final Signal</p>

                  {analysis.direction ? (
                    <>
                      <p className={`text-4xl font-black mb-2 ${analysis.direction === "LONG" ? "text-green-600" : "text-red-500"}`}>
                        {analysis.direction === "LONG" ? "🟢 BUY" : "🔴 SELL"}
                      </p>
                      <p className="text-sm text-muted-foreground mb-4">
                        Confidence: <strong>{analysis.confidence?.toFixed(0)}%</strong>
                      </p>
                      <div className="grid grid-cols-3 gap-3 text-left">
                        <div className="bg-white rounded-xl p-3 border shadow-sm">
                          <p className="text-xs text-muted-foreground">Entry Price</p>
                          <p className="font-bold text-base">${fmtPrice(analysis.entry!)}</p>
                        </div>
                        <div className="bg-white rounded-xl p-3 border border-red-200 shadow-sm">
                          <p className="text-xs text-red-500">Stop Loss</p>
                          <p className="font-bold text-base text-red-600">${fmtPrice(analysis.stop_loss!)}</p>
                        </div>
                        <div className="bg-white rounded-xl p-3 border border-green-200 shadow-sm">
                          <p className="text-xs text-green-600">Take Profit</p>
                          <p className="font-bold text-base text-green-600">${fmtPrice(analysis.take_profit!)}</p>
                        </div>
                      </div>
                      <p className="text-sm mt-3 text-muted-foreground">
                        Risk:Reward = <strong className="text-primarygreen text-base">{analysis.risk_reward}</strong>
                      </p>
                    </>
                  ) : (
                    <>
                      <p className="text-3xl font-black text-neutral-500 mb-2">⏸ NO SIGNAL</p>
                      <p className="text-sm text-muted-foreground bg-white/70 rounded-lg px-4 py-2 inline-block">
                        {analysis.skip_reason}
                      </p>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
