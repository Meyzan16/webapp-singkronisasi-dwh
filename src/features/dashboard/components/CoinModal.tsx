"use client";
import { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { CandlestickChart } from "@/components/ui/candlestick-chart";

interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number; }
interface CoinInfo {
  symbol: string; last_price: number; mark_price: number; index_price: number;
  change_24h: number; high_24h: number; low_24h: number; volume_24h: number;
  quote_volume_24h: number; open_interest: number; funding_rate: number;
  next_funding_time: number; count_24h: number;
}
interface TALayer { name: string; timeframe: string; status: string; signal?: string; detail?: string; }
interface TakeProfit { level: number; price: number; rr: string; basis: string; }
interface Analysis {
  direction: string | null; entry: number | null; stop_loss: number | null;
  sl_basis: string | null; take_profits: TakeProfit[];
  risk_reward: string | null; confidence: number | null;
  skip_reason: string | null; layers: TALayer[];
  timeframes: Record<string, string>;
  style: string;
}

// ── Trading styles ────────────────────────────────────────────────────────────
const STYLES = [
  {
    key: "scalping",
    label: "Scalping",
    icon: "⚡",
    desc: "Minutes–Hours",
    tfs: "T0:4H → T1:1H → T2:1H → T3:15M → T4:15M",
    color: "from-yellow-500 to-orange-500",
  },
  {
    key: "daytrading",
    label: "Day Trade",
    icon: "📅",
    desc: "Intraday",
    tfs: "T0:1D → T1:4H → T2:4H → T3:1H → T4:1H",
    color: "from-blue-500 to-indigo-500",
  },
  {
    key: "swing",
    label: "Swing",
    icon: "🌊",
    desc: "Days–Weeks",
    tfs: "T0:1W → T1:1D → T2:1D → T3:4H → T4:4H",
    color: "from-primarygreen to-teal-500",
  },
  {
    key: "position",
    label: "Position",
    icon: "🏔",
    desc: "Weeks–Months",
    tfs: "T0:1W → T1:1W → T2:1D → T3:1D → T4:1D",
    color: "from-purple-500 to-violet-500",
  },
] as const;

type StyleKey = typeof STYLES[number]["key"];

const PIPELINE_STEPS = [
  { layer: "T0", name: "T0 Wyckoff",   icon: "🌀", desc: "Phase"    },
  { layer: "T1", name: "T1 Trend",     icon: "📈", desc: "EMA Trend" },
  { layer: "T2", name: "T2 S/R Zones", icon: "🏔", desc: "S/R Zones" },
  { layer: "T3", name: "T3 Pattern",   icon: "🔷", desc: "Pattern"   },
  { layer: "T4", name: "T4 Trigger",   icon: "⚡", desc: "Trigger"   },
];

// Chart timeframe matches the T4 trigger timeframe per style
const STYLE_CHART_TF: Record<StyleKey, string> = {
  scalping:   "15m",
  daytrading: "1h",
  swing:      "4h",
  position:   "1d",
};

type PipelineStatus = "idle" | "running" | "done" | "error";

interface CoinModalProps { symbol: string; onClose: () => void; }

export function CoinModal({ symbol, onClose }: CoinModalProps) {
  const [tab, setTab] = useState<"chart" | "info" | "analysis">("chart");
  const [style, setStyle] = useState<StyleKey>("swing");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [info, setInfo] = useState<CoinInfo | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus>("idle");
  const [visibleLayers, setVisibleLayers] = useState(0);
  const [loadingCandles, setLoadingCandles] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const base = symbol.replace("USDT", "");
  const chartTf = STYLE_CHART_TF[style];

  const fetchCandles = useCallback(async (tf: string) => {
    setLoadingCandles(true);
    try {
      const limit = tf === "15m" ? 200 : tf === "1h" ? 150 : tf === "4h" ? 120 : 100;
      const r = await fetch(`/api/v1/coin/${symbol}/klines?interval=${tf}&limit=${limit}`);
      const d = await r.json();
      setCandles(d.candles ?? []);
    } catch { /* silent */ }
    finally { setLoadingCandles(false); }
  }, [symbol]);

  useEffect(() => { void fetchCandles(chartTf); }, [chartTf, fetchCandles]);

  const fetchInfo = useCallback(async () => {
    try {
      const r = await fetch(`/api/v1/coin/${symbol}/info`);
      setInfo(await r.json());
    } catch { /* silent */ }
  }, [symbol]);

  useEffect(() => { void fetchInfo(); }, [fetchInfo]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const runAnalysis = async (s: StyleKey) => {
    setPipelineStatus("running");
    setAnalysis(null);
    setVisibleLayers(0);
    setError(null);

    try {
      const r = await fetch(`/api/v1/coin/${symbol}/analyze?style=${s}`);
      const data: Analysis & { detail?: string } = await r.json();

      if (!r.ok || data.detail) {
        setError(data.detail ?? "Analysis failed");
        setPipelineStatus("error");
        return;
      }

      // Animate layers one by one
      const layers = data.layers ?? [];
      for (let i = 0; i < layers.length; i++) {
        await new Promise(res => setTimeout(res, 550));
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
    status === "passed"     ? "bg-green-50 border-green-300 text-green-800"
    : status === "failed"   ? "bg-red-50 border-red-300 text-red-800"
    : status === "gate_failed" ? "bg-orange-50 border-orange-400 text-orange-800"
    : status === "blocked"  ? "bg-neutral-100 border-neutral-200 text-neutral-400 opacity-60"
    : "bg-neutral-50 border-neutral-200 text-neutral-600";

  const layerIcon = (status: string) =>
    status === "passed"     ? "✓"
    : status === "failed"   ? "✗"
    : status === "gate_failed" ? "⛔"
    : status === "blocked"  ? "—"
    : "~";

  const getLayer = (name: string) => analysis?.layers?.find(l => l.name === name);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[93vh] flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 bg-gradient-to-r from-primarygreen to-teal-500 text-white flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-white/20 flex items-center justify-center font-bold text-xs">
              {base.slice(0, 3)}
            </div>
            <div>
              <h2 className="text-lg font-bold leading-tight">{base}/USDT</h2>
              <p className="text-xs opacity-70">Futures Perpetual</p>
            </div>
          </div>
          {info && (
            <div className="text-right">
              <p className="text-xl font-bold">${fmtPrice(info.last_price)}</p>
              <p className={`text-xs font-semibold ${info.change_24h >= 0 ? "text-green-200" : "text-red-200"}`}>
                {info.change_24h >= 0 ? "▲" : "▼"} {Math.abs(info.change_24h).toFixed(2)}%
              </p>
            </div>
          )}
          <button onClick={onClose} className="ml-3 w-7 h-7 rounded-full bg-white/20 hover:bg-white/30 flex items-center justify-center text-lg">×</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b px-5 bg-neutral-50 flex-shrink-0">
          {(["chart", "info", "analysis"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-2.5 text-sm font-semibold capitalize border-b-2 transition-colors ${tab === t ? "border-primarygreen text-primarygreen" : "border-transparent text-muted-foreground hover:text-black"}`}>
              {t === "chart" ? "📈 Chart" : t === "info" ? "📊 Info" : "🤖 TA Analysis"}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">

          {/* ── CHART ── */}
          {tab === "chart" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex gap-2">
                  {(["15m","1h","4h","1d","1w"] as const).map((tf) => (
                    <button key={tf} onClick={() => void fetchCandles(tf)}
                      className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors ${chartTf === tf ? "bg-primarygreen text-white" : "bg-neutral-100 hover:bg-neutral-200"}`}>
                      {tf.toUpperCase()}
                    </button>
                  ))}
                </div>
                {loadingCandles && <span className="text-xs text-muted-foreground animate-pulse">Loading...</span>}
              </div>
              {candles.length > 0 && !loadingCandles && <CandlestickChart candles={candles} height={350} />}
            </div>
          )}

          {/* ── MARKET INFO ── */}
          {tab === "info" && info && (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {[
                { label: "Last Price",    value: `$${fmtPrice(info.last_price)}` },
                { label: "Mark Price",    value: `$${fmtPrice(info.mark_price)}` },
                { label: "Index Price",   value: `$${fmtPrice(info.index_price)}` },
                { label: "24h Change",    value: `${info.change_24h >= 0 ? "+" : ""}${info.change_24h.toFixed(2)}%`, color: info.change_24h >= 0 ? "text-green-600" : "text-red-500" },
                { label: "24h High",      value: `$${fmtPrice(info.high_24h)}`, color: "text-green-600" },
                { label: "24h Low",       value: `$${fmtPrice(info.low_24h)}`, color: "text-red-500" },
                { label: "Volume (USDT)", value: fmtVol(info.quote_volume_24h) },
                { label: "Open Interest", value: info.open_interest.toLocaleString() },
                { label: "Funding Rate",  value: `${info.funding_rate}%`, color: info.funding_rate >= 0 ? "text-green-600" : "text-red-500" },
                { label: "Trades (24h)",  value: info.count_24h.toLocaleString() },
                { label: "Next Funding",  value: info.next_funding_time ? new Date(info.next_funding_time).toLocaleTimeString() : "—" },
                { label: "Volume (coin)", value: info.volume_24h.toLocaleString() },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-neutral-50 rounded-xl p-3 border">
                  <p className="text-xs text-muted-foreground mb-1">{label}</p>
                  <p className={`text-base font-bold ${color ?? ""}`}>{value}</p>
                </div>
              ))}
            </div>
          )}

          {/* ── TA ANALYSIS ── */}
          {tab === "analysis" && (
            <div className="space-y-4">

              {/* Trading Style selector */}
              <div>
                <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">Trading Style</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {STYLES.map((s) => (
                    <button key={s.key}
                      onClick={() => { setStyle(s.key); setPipelineStatus("idle"); setAnalysis(null); setVisibleLayers(0); }}
                      className={`p-3 rounded-xl border-2 text-left transition-all ${
                        style === s.key
                          ? "border-primarygreen bg-primarygreen/5 shadow-sm"
                          : "border-neutral-200 hover:border-neutral-300 bg-white"
                      }`}>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-lg">{s.icon}</span>
                        <span className="font-bold text-sm">{s.label}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">{s.desc}</p>
                      <p className="text-[10px] text-muted-foreground mt-1 font-mono opacity-70 truncate">{s.tfs}</p>
                    </button>
                  ))}
                </div>
              </div>

              {/* Run button */}
              <button
                onClick={() => void runAnalysis(style)}
                disabled={pipelineStatus === "running"}
                className="w-full py-3 bg-primarygreen text-white rounded-xl font-bold text-sm hover:bg-teal-600 disabled:opacity-50 flex items-center justify-center gap-2 shadow-sm"
              >
                {pipelineStatus === "running"
                  ? <><span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />Analyzing {base} ({STYLES.find(s => s.key === style)?.label})...</>
                  : `▶ Run ${STYLES.find(s => s.key === style)?.label} Analysis — ${base}/USDT`}
              </button>

              {/* Idle */}
              {pipelineStatus === "idle" && (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-4xl mb-2">🤖</p>
                  <p className="font-semibold">Select a trading style and click Run</p>
                  <p className="text-xs mt-1 opacity-70">Each style uses different timeframes for T0→T4</p>
                </div>
              )}

              {/* Error */}
              {pipelineStatus === "error" && error && (
                <div className="bg-red-50 border border-red-300 rounded-xl p-4 text-red-800 text-sm">
                  <strong>Error:</strong> {error}
                </div>
              )}

              {/* Pipeline animation */}
              {(pipelineStatus === "running" || pipelineStatus === "done") && (
                <div className="space-y-3">

                  {/* Step bubbles */}
                  <div className="flex items-center justify-between px-2">
                    {PIPELINE_STEPS.map((step, i) => {
                      const layer = getLayer(step.name);
                      const isVisible = i < visibleLayers;
                      const isCurrent = i === visibleLayers && pipelineStatus === "running";
                      const status = layer?.status ?? (isCurrent ? "running" : "idle");
                      const tf = analysis?.timeframes?.[`t${i}`] ?? "";

                      return (
                        <div key={step.name} className="flex items-center gap-0">
                          <div className={`flex flex-col items-center transition-all duration-500 ${isVisible ? "opacity-100" : "opacity-25"}`}>
                            <div className={`w-11 h-11 rounded-full flex items-center justify-center text-lg border-2 transition-all duration-300 ${
                              isCurrent        ? "border-primarygreen bg-primarygreen/10 animate-pulse"
                              : status === "passed"      ? "border-green-500 bg-green-50"
                              : status === "failed"      ? "border-red-400 bg-red-50"
                              : status === "gate_failed" ? "border-orange-400 bg-orange-50"
                              : status === "blocked"     ? "border-neutral-200 bg-neutral-100 opacity-40"
                              : status === "skipped"     ? "border-neutral-300 bg-neutral-50"
                              : "border-neutral-200 bg-white"
                            }`}>
                              {isCurrent             ? <span className="text-primarygreen animate-spin inline-block">⟳</span>
                                : status === "passed"      ? <span className="text-green-600 font-bold text-base">✓</span>
                                : status === "failed"      ? <span className="text-red-500 font-bold text-base">✗</span>
                                : status === "gate_failed" ? <span className="text-orange-500 font-bold text-base">⛔</span>
                                : status === "blocked"     ? <span className="text-neutral-400 text-base">—</span>
                                : <span>{step.icon}</span>}
                            </div>
                            <p className="text-xs font-bold mt-1">{step.layer}</p>
                            {tf && <span className="text-[10px] bg-neutral-100 px-1.5 py-0.5 rounded font-mono text-neutral-500 mt-0.5">{tf.toUpperCase()}</span>}
                            <p className="text-[10px] text-muted-foreground">{step.desc}</p>
                          </div>
                          {i < PIPELINE_STEPS.length - 1 && (
                            <div className={`w-8 h-0.5 mx-1 mb-6 transition-all duration-500 ${isVisible && i + 1 < visibleLayers ? "bg-primarygreen" : "bg-neutral-200"}`} />
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {/* Layer cards */}
                  <div className="space-y-2">
                    {PIPELINE_STEPS.map((step, i) => {
                      const layer = getLayer(step.name);
                      if (i >= visibleLayers || !layer) return null;
                      return (
                        <div key={step.name}
                          className={`p-3 rounded-xl border flex items-start gap-3 ${layerBg(layer.status)}`}>
                          <span className="font-bold w-5 text-center flex-shrink-0 text-sm">
                            {layerIcon(layer.status)}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-semibold text-sm">{layer.name}</span>
                              <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0">{layer.timeframe}</Badge>
                              {layer.signal && layer.signal !== "No chart pattern" && (
                                <Badge variant="outline" className="text-xs">{layer.signal}</Badge>
                              )}
                            </div>
                            {layer.detail && <p className="text-xs mt-0.5 opacity-80 leading-relaxed">{layer.detail}</p>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Final result */}
              {pipelineStatus === "done" && analysis && (
                <div className={`rounded-2xl border-2 overflow-hidden ${
                  analysis.direction === "LONG"  ? "border-green-400"
                  : analysis.direction === "SHORT" ? "border-red-400"
                  : "border-neutral-300"
                }`}>
                  {/* Signal header */}
                  <div className={`px-5 py-4 text-center ${
                    analysis.direction === "LONG"  ? "bg-green-50"
                    : analysis.direction === "SHORT" ? "bg-red-50"
                    : "bg-neutral-50"
                  }`}>
                    <p className="text-xs uppercase tracking-wider text-muted-foreground font-semibold mb-1">
                      {STYLES.find(s => s.key === analysis.style)?.label} Signal
                    </p>
                    {analysis.direction ? (
                      <>
                        <p className={`text-4xl font-black ${analysis.direction === "LONG" ? "text-green-600" : "text-red-500"}`}>
                          {analysis.direction === "LONG" ? "🟢 BUY" : "🔴 SELL"}
                        </p>
                        <p className="text-sm text-muted-foreground mt-1">
                          Confidence: <strong>{analysis.confidence?.toFixed(0)}%</strong>
                        </p>
                      </>
                    ) : (
                      <>
                        <p className="text-3xl font-black text-neutral-500">⏸ NO SIGNAL</p>
                        <p className="text-xs text-muted-foreground mt-2 px-4">{analysis.skip_reason}</p>
                      </>
                    )}
                  </div>

                  {/* Trade levels — only when signal */}
                  {analysis.direction && (
                    <div className="bg-white px-5 py-4 space-y-3">
                      {/* Entry + SL row */}
                      <div className="grid grid-cols-2 gap-3">
                        <div className="bg-neutral-50 rounded-xl p-3 border">
                          <p className="text-xs text-muted-foreground">Entry Price</p>
                          <p className="font-bold text-base">${fmtPrice(analysis.entry!)}</p>
                        </div>
                        <div className="bg-red-50 rounded-xl p-3 border border-red-200">
                          <p className="text-xs text-red-500">Stop Loss ⛔</p>
                          <p className="font-bold text-base text-red-600">${fmtPrice(analysis.stop_loss!)}</p>
                          {analysis.sl_basis && <p className="text-[10px] text-red-400 mt-0.5">{analysis.sl_basis}</p>}
                        </div>
                      </div>

                      {/* Multi-TP */}
                      {analysis.take_profits && analysis.take_profits.length > 0 && (
                        <div>
                          <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">Take Profit Targets</p>
                          <div className="space-y-2">
                            {analysis.take_profits.map((tp) => (
                              <div key={tp.level} className="flex items-center justify-between bg-green-50 rounded-xl px-4 py-2.5 border border-green-200">
                                <div className="flex items-center gap-3">
                                  <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white ${
                                    tp.level === 1 ? "bg-green-400" : tp.level === 2 ? "bg-green-500" : "bg-green-600"
                                  }`}>
                                    T{tp.level}
                                  </div>
                                  <div>
                                    <p className="font-bold text-green-700 text-sm">${fmtPrice(tp.price)}</p>
                                    <p className="text-[10px] text-green-600">{tp.basis}</p>
                                  </div>
                                </div>
                                <span className="text-xs font-bold text-primarygreen bg-white px-2 py-1 rounded-lg border border-primarygreen/30">
                                  R:R {tp.rr}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
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
