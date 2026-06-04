"use client";
import { useEffect, useState, useCallback } from "react";
import { fmtPriceShort } from "@/lib/format";
import { CoinChartTab }      from "./coin-modal/CoinChartTab";
import { CoinInfoTab }       from "./coin-modal/CoinInfoTab";
import { PipelineAnimation } from "./coin-modal/PipelineAnimation";
import { AnalysisResult }    from "./coin-modal/AnalysisResult";
import { STYLES, STYLE_CHART_TF } from "./coin-modal/types";
import type { Candle, CoinInfo, Analysis, PipelineStatus, StyleKey } from "./coin-modal/types";

type TabKey = "chart" | "info" | "analysis";

interface CoinModalProps { symbol: string; onClose: () => void; }

export function CoinModal({ symbol, onClose }: CoinModalProps) {
  const [tab, setTab]                     = useState<TabKey>("chart");
  const [style, setStyle]                 = useState<StyleKey>("swing");
  const [candles, setCandles]             = useState<Candle[]>([]);
  const [info, setInfo]                   = useState<CoinInfo | null>(null);
  const [analysis, setAnalysis]           = useState<Analysis | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus>("idle");
  const [visibleLayers, setVisibleLayers] = useState(0);
  const [loadingCandles, setLoadingCandles] = useState(true);
  const [error, setError]                 = useState<string | null>(null);

  const base    = symbol.replace("USDT", "");
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

  const fetchInfo = useCallback(async () => {
    try {
      const r = await fetch(`/api/v1/coin/${symbol}/info`);
      setInfo(await r.json());
    } catch { /* silent */ }
  }, [symbol]);

  useEffect(() => { void fetchCandles(chartTf); }, [chartTf, fetchCandles]);
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
      if (!r.ok || data.detail) { setError(data.detail ?? "Analysis failed"); setPipelineStatus("error"); return; }
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

  const selectStyle = (key: StyleKey) => {
    setStyle(key);
    setPipelineStatus("idle");
    setAnalysis(null);
    setVisibleLayers(0);
  };

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
              <p className="text-xl font-bold">${fmtPriceShort(info.last_price)}</p>
              <p className={`text-xs font-semibold ${info.change_24h >= 0 ? "text-green-200" : "text-red-200"}`}>
                {info.change_24h >= 0 ? "▲" : "▼"} {Math.abs(info.change_24h).toFixed(2)}%
              </p>
            </div>
          )}
          <button onClick={onClose} className="ml-3 w-7 h-7 rounded-full bg-white/20 hover:bg-white/30 flex items-center justify-center text-lg">×</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b px-5 bg-neutral-50 flex-shrink-0">
          {(["chart", "info", "analysis"] as TabKey[]).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-2.5 text-sm font-semibold capitalize border-b-2 transition-colors ${
                tab === t ? "border-primarygreen text-primarygreen" : "border-transparent text-muted-foreground hover:text-black"
              }`}>
              {t === "chart" ? "📈 Chart" : t === "info" ? "📊 Info" : "🤖 TA Analysis"}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
          {tab === "chart" && (
            <CoinChartTab
              candles={candles}
              loading={loadingCandles}
              analysis={analysis}
              chartTf={chartTf}
              onTfChange={tf => void fetchCandles(tf)}
            />
          )}

          {tab === "info" && info && <CoinInfoTab info={info} />}

          {tab === "analysis" && (
            <div className="space-y-4">
              {/* Style selector */}
              <div>
                <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">Trading Style</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {STYLES.map(s => (
                    <button key={s.key} onClick={() => selectStyle(s.key)}
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
              <button onClick={() => void runAnalysis(style)} disabled={pipelineStatus === "running"}
                className="w-full py-3 bg-primarygreen text-white rounded-xl font-bold text-sm hover:bg-teal-600 disabled:opacity-50 flex items-center justify-center gap-2 shadow-sm">
                {pipelineStatus === "running"
                  ? <><span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />Analyzing {base} ({STYLES.find(s => s.key === style)?.label})...</>
                  : `▶ Run ${STYLES.find(s => s.key === style)?.label} Analysis — ${base}/USDT`}
              </button>

              {pipelineStatus === "idle" && (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-4xl mb-2">🤖</p>
                  <p className="font-semibold">Select a trading style and click Run</p>
                  <p className="text-xs mt-1 opacity-70">Each style uses different timeframes for T0→T4</p>
                </div>
              )}

              {pipelineStatus === "error" && error && (
                <div className="bg-red-50 border border-red-300 rounded-xl p-4 text-red-800 text-sm">
                  <strong>Error:</strong> {error}
                </div>
              )}

              {(pipelineStatus === "running" || pipelineStatus === "done") && (
                <PipelineAnimation
                  pipelineStatus={pipelineStatus}
                  visibleLayers={visibleLayers}
                  analysis={analysis}
                />
              )}

              {pipelineStatus === "done" && analysis && (
                <AnalysisResult analysis={analysis} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
