"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries, IChartApi, ISeriesApi } from "lightweight-charts";

interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number; }

type DrawTool = "none" | "hline" | "rect" | "fib";

interface TradingChartProps {
  candles: Candle[];
  height?: number;
  entryPrice?: number;
  stopLoss?: number;
  takeProfits?: { price: number; level: number }[];
}

export function TradingChart({ candles, height = 420, entryPrice, stopLoss, takeProfits }: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [tool, setTool] = useState<DrawTool>("none");
  const [drawings, setDrawings] = useState<{ type: DrawTool; price?: number; label?: string }[]>([]);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;

    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#0f0f0f" }, textColor: "#9ca3af" },
      grid: { vertLines: { color: "#1f2937" }, horzLines: { color: "#1f2937" } },
      width: containerRef.current.clientWidth,
      height,
      crosshair: { mode: 1 },
      timeScale: { borderColor: "#374151", timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "#374151" },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#14b8a6", downColor: "#ef4444",
      borderUpColor: "#14b8a6", borderDownColor: "#ef4444",
      wickUpColor: "#14b8a6", wickDownColor: "#ef4444",
    });
    candleSeriesRef.current = candleSeries;

    const volSeries = chart.addSeries(HistogramSeries, {
      color: "#14b8a626", priceFormat: { type: "volume" as const }, priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    const sorted = [...candles].sort((a, b) => a.time - b.time);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    candleSeries.setData(sorted.map(c => ({ time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close })));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    volSeries.setData(sorted.map(c => ({ time: c.time as any, value: c.volume, color: c.close >= c.open ? "#14b8a640" : "#ef444440" })));

    // ── Trade levels ──────────────────────────────────────────────────────────
    const t0 = sorted[0].time as any; // eslint-disable-line @typescript-eslint/no-explicit-any
    const t1 = sorted[sorted.length - 1].time as any; // eslint-disable-line @typescript-eslint/no-explicit-any

    if (entryPrice && sorted.length) {
      // Entry zone: shaded band ±0.3% around entry (thick line approximation)
      const entryBuf = entryPrice * 0.003;
      const entryTop = chart.addSeries(LineSeries, {
        color: "#facc1540", lineWidth: 8, lineStyle: 0, priceScaleId: "right",
        lastValueVisible: false, priceLineVisible: false,
      });
      entryTop.setData([{ time: t0, value: entryPrice + entryBuf }, { time: t1, value: entryPrice + entryBuf }]);

      const entryBot = chart.addSeries(LineSeries, {
        color: "#facc1540", lineWidth: 8, lineStyle: 0, priceScaleId: "right",
        lastValueVisible: false, priceLineVisible: false,
      });
      entryBot.setData([{ time: t0, value: entryPrice - entryBuf }, { time: t1, value: entryPrice - entryBuf }]);

      // Entry center line (solid)
      const entryLine = chart.addSeries(LineSeries, {
        color: "#facc15", lineWidth: 2, lineStyle: 0, priceScaleId: "right",
        lastValueVisible: true, title: "Entry",
      });
      entryLine.setData([{ time: t0, value: entryPrice }, { time: t1, value: entryPrice }]);
    }

    if (stopLoss && sorted.length) {
      // SL zone band
      const slBuf = Math.abs(entryPrice ? (entryPrice - stopLoss) * 0.1 : stopLoss * 0.003);
      const slTop = chart.addSeries(LineSeries, {
        color: "#ef444430", lineWidth: 6, lineStyle: 0, priceScaleId: "right",
        lastValueVisible: false, priceLineVisible: false,
      });
      slTop.setData([{ time: t0, value: stopLoss + slBuf }, { time: t1, value: stopLoss + slBuf }]);
      const slBot = chart.addSeries(LineSeries, {
        color: "#ef444430", lineWidth: 6, lineStyle: 0, priceScaleId: "right",
        lastValueVisible: false, priceLineVisible: false,
      });
      slBot.setData([{ time: t0, value: stopLoss - slBuf }, { time: t1, value: stopLoss - slBuf }]);

      const slLine = chart.addSeries(LineSeries, {
        color: "#ef4444", lineWidth: 2, lineStyle: 2, priceScaleId: "right",
        lastValueVisible: true, title: "SL",
      });
      slLine.setData([{ time: t0, value: stopLoss }, { time: t1, value: stopLoss }]);
    }

    takeProfits?.forEach((tp, idx) => {
      if (!sorted.length) return;
      const tpColors = ["#22c55e", "#16a34a", "#14532d"];
      const color = tpColors[idx] ?? "#22c55e";
      const tpLine = chart.addSeries(LineSeries, {
        color, lineWidth: 1, lineStyle: 2, priceScaleId: "right",
        lastValueVisible: true, title: `TP${tp.level}`,
      });
      tpLine.setData([{ time: t0, value: tp.price }, { time: t1, value: tp.price }]);
    });

    chart.timeScale().fitContent();

    const handleResize = () => { if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth }); };
    window.addEventListener("resize", handleResize);
    return () => { window.removeEventListener("resize", handleResize); chart.remove(); chartRef.current = null; };
  }, [candles, height, entryPrice, stopLoss, takeProfits]);

  // Click to draw horizontal line
  const handleChartClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (tool === "none" || !chartRef.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const y = e.clientY - rect.top;
    const price = chartRef.current.priceScale("right").coordinateToPrice(y);
    if (!price || !candleSeriesRef.current) return;

    if (tool === "hline") {
      const label = prompt("Label (optional):", "Level");
      setDrawings(prev => [...prev, { type: "hline", price, label: label ?? undefined }]);
      // Add to chart
      const sorted = [...candles].sort((a, b) => a.time - b.time);
      if (sorted.length) {
        const line = chartRef.current.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, lineStyle: 1 });
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        line.setData([{ time: sorted[0].time as any, value: price }, { time: sorted[sorted.length - 1].time as any, value: price }]);
      }
    } else if (tool === "fib") {
      // Simple: draw fib from last swing low to clicked price
      const sorted = [...candles].sort((a, b) => a.time - b.time);
      const recent = sorted.slice(-20);
      const low = Math.min(...recent.map(c => c.low));
      const high = price;
      const diff = high - low;
      [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].forEach(level => {
        const lvlPrice = high - diff * level;
        const l = chartRef.current!.addSeries(LineSeries, {
          color: level === 0.618 ? "#f59e0b" : "#6366f1",
          lineWidth: 1, lineStyle: 2,
        });
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        l.setData([{ time: sorted[0].time as any, value: lvlPrice }, { time: sorted[sorted.length - 1].time as any, value: lvlPrice }]);
      });
      setDrawings(prev => [...prev, { type: "fib", price }]);
      setTool("none");
    }
  }, [tool, candles]);

  const clearDrawings = () => {
    setDrawings([]);
    // Re-render chart by toggling
    if (containerRef.current) containerRef.current.dispatchEvent(new Event("resize"));
  };

  const TOOLS = [
    { key: "none" as DrawTool, icon: "↖", label: "Select" },
    { key: "hline" as DrawTool, icon: "—", label: "H-Line" },
    { key: "fib" as DrawTool, icon: "φ", label: "Fibonacci" },
  ];

  return (
    <div className="relative select-none">
      {/* Toolbar */}
      <div className="flex items-center gap-1 mb-2">
        <div className="flex bg-neutral-900 rounded-lg p-0.5 gap-0.5">
          {TOOLS.map(t => (
            <button key={t.key} onClick={() => setTool(t.key)}
              title={t.label}
              className={`px-2.5 py-1 rounded text-xs font-mono transition-colors ${
                tool === t.key ? "bg-primarygreen text-white" : "text-neutral-400 hover:text-white hover:bg-neutral-700"
              }`}>
              {t.icon}
            </button>
          ))}
        </div>
        {drawings.length > 0 && (
          <button onClick={clearDrawings}
            className="px-2 py-1 text-xs bg-neutral-800 text-neutral-400 hover:text-red-400 rounded-lg transition-colors">
            🗑 Clear
          </button>
        )}
        {tool !== "none" && (
          <span className="text-xs text-amber-400 bg-amber-400/10 px-2 py-1 rounded-lg">
            {tool === "hline" ? "Click chart to draw horizontal line" : "Click chart to draw Fibonacci"}
          </span>
        )}
        {entryPrice && (
          <div className="ml-auto flex gap-3 text-xs">
            <span className="text-yellow-400">— Entry</span>
            <span className="text-red-400">— SL</span>
            <span className="text-green-400">— TP</span>
          </div>
        )}
      </div>

      {/* Chart canvas */}
      <div
        ref={containerRef}
        className={`w-full rounded-xl overflow-hidden ${tool !== "none" ? "cursor-crosshair" : "cursor-default"}`}
        onClick={handleChartClick}
      />
    </div>
  );
}
