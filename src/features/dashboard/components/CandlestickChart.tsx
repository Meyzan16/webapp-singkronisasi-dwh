"use client";
import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  CandlestickSeries,
  HistogramSeries,
} from "lightweight-charts";

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface CandlestickChartProps {
  candles: Candle[];
  height?: number;
}

export function CandlestickChart({ candles, height = 320 }: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#6b7280",
      },
      grid: {
        vertLines: { color: "#f3f4f6" },
        horzLines: { color: "#f3f4f6" },
      },
      width: containerRef.current.clientWidth,
      height,
      timeScale: {
        borderColor: "#e5e7eb",
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: { borderColor: "#e5e7eb" },
    });

    // v5 API: addSeries(SeriesType, options)
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#14b8a6",
      downColor: "#ef4444",
      borderUpColor: "#14b8a6",
      borderDownColor: "#ef4444",
      wickUpColor: "#14b8a6",
      wickDownColor: "#ef4444",
    });

    const volSeries = chart.addSeries(HistogramSeries, {
      color: "#14b8a626",
      priceFormat: { type: "volume" as const },
      priceScaleId: "volume",
    });

    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    const sorted = [...candles].sort((a, b) => a.time - b.time);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    candleSeries.setData(sorted.map((c) => ({ time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close })));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    volSeries.setData(sorted.map((c) => ({ time: c.time as any, value: c.volume, color: c.close >= c.open ? "#14b8a640" : "#ef444440" })));

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [candles, height]);

  return <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />;
}
