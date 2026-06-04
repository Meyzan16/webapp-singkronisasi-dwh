"use client";
import { useEffect, useState, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StyleSelector }  from "./scanner/StyleSelector";
import { DirectionFilter } from "./scanner/DirectionFilter";
import { ScannerFilters }  from "./scanner/ScannerFilters";
import { SignalCard, ALERT_BADGES, ALERT_LABELS } from "./scanner/SignalCard";
import type { ScanSignal, ScannerData } from "@/types/scanner";

interface ScannerWidgetProps { fullPage?: boolean; }

export function ScannerWidget({ fullPage = false }: ScannerWidgetProps) {
  const [data, setData]         = useState<ScannerData | null>(null);
  const [loading, setLoading]   = useState(true);
  const [style, setStyle]       = useState("swing");

  // Filters (client-side, no extra API call)
  const [direction, setDirection] = useState<"ALL" | "LONG" | "SHORT">("ALL");
  const [search, setSearch]       = useState("");
  const [alertType, setAlertType] = useState("ALL");
  const [minProb, setMinProb]     = useState(0);
  const [minRR, setMinRR]         = useState(3); // default 1:3

  const fetchData = useCallback(async (s: string) => {
    try {
      setLoading(true);
      const r = await fetch(`/api/v1/scanner/scan?style=${s}`);
      if (r.ok) setData(await r.json());
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void fetchData(style);
    const t = setInterval(() => void fetchData(style), 5 * 60 * 1000);
    return () => clearInterval(t);
  }, [fetchData, style]);

  const handleStyleChange = (s: string) => {
    setStyle(s);
    // Reset filters on style change
    setSearch("");
    setAlertType("ALL");
    setDirection("ALL");
    setMinProb(0);
    setMinRR(3);
    void fetchData(s);
  };

  // Apply all filters client-side
  const allResults = data?.results ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return allResults.filter(r => {
      if (direction !== "ALL" && r.direction !== direction) return false;
      if (alertType !== "ALL" && r.alert_type !== alertType) return false;
      if (r.probability < minProb) return false;
      if (q && !r.symbol.toLowerCase().includes(q)) return false;
      // R:R filter — parse "1:3.5" → 3.5
      const rrVal = parseFloat(r.risk_reward?.split(":")?.[1] ?? "0");
      if (rrVal < minRR) return false;
      return true;
    });
  }, [allResults, direction, alertType, minProb, minRR, search]);

  const timeAgo    = data ? Math.floor((Date.now() / 1000 - data.generated_at) / 60) : 0;
  const longCount  = allResults.filter(r => r.direction === "LONG").length;
  const shortCount = allResults.filter(r => r.direction === "SHORT").length;
  const hasFilters = search !== "" || alertType !== "ALL" || minProb > 0 || direction !== "ALL" || minRR > 3;

  return (
    <Card className="border-0 bg-neutral-950 text-white">
      <CardHeader className="pb-3">
        <CardTitle className="space-y-3">

          {/* Title + meta row */}
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-xl">🔭</span>
              <div>
                <p className="text-sm font-bold leading-tight">Early Breakout Scanner</p>
                <p className="text-[10px] text-neutral-500 font-normal">
                  Detects coiling, accumulation & breakout zones
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {loading && (
                <span className="animate-spin w-3 h-3 border-2 border-teal-400 border-t-transparent rounded-full" />
              )}
              {data && !loading && (
                <span className="text-[10px] text-neutral-500">
                  {data.style_label} ({data.timeframe}) · {data.scanned} pairs ·{" "}
                  {timeAgo === 0 ? "baru" : `${timeAgo}m lalu`}
                </span>
              )}
              <button
                onClick={() => void fetchData(style)}
                className="text-xs bg-neutral-800 hover:bg-neutral-700 px-2 py-1 rounded-lg transition-colors text-neutral-300">
                ↻
              </button>
            </div>
          </div>

          {/* Trading style tabs */}
          <StyleSelector active={style} onChange={handleStyleChange} />

          {/* Direction filter */}
          <DirectionFilter
            active={direction}
            total={allResults.length}
            longCount={longCount}
            shortCount={shortCount}
            onChange={setDirection}
          />

          {/* Search + alert type + min prob */}
          <ScannerFilters
            search={search}
            alertType={alertType}
            minProb={minProb}
            minRR={minRR}
            resultCount={filtered.length}
            totalCount={allResults.length}
            onSearch={setSearch}
            onAlertType={setAlertType}
            onMinProb={setMinProb}
            onMinRR={setMinRR}
          />

        </CardTitle>
      </CardHeader>

      <CardContent className="pt-0">
        {/* Legend */}
        {fullPage && (
          <div className="flex gap-3 mb-3 flex-wrap text-[10px] text-neutral-500">
            {Object.entries(ALERT_LABELS).map(([key, label]) => (
              <span key={key} className="flex items-center gap-1">
                <span className={`w-2 h-2 rounded-full ${ALERT_BADGES[key]}`} />
                {label}
              </span>
            ))}
            <span className="ml-auto">Probability bar = chance of big move soon</span>
          </div>
        )}

        {/* Loading state */}
        {loading && !data && (
          <div className="py-10 text-center text-neutral-500 text-sm">
            <div className="animate-pulse space-y-1">
              <p>🔭 Scanning 100 most active pairs...</p>
              <p className="text-[10px]">Detecting coils, accumulation & breakout zones</p>
            </div>
          </div>
        )}

        {/* Active filter info */}
        {!loading && data && hasFilters && (
          <div className="flex items-center justify-between mb-2">
            <p className="text-[10px] text-neutral-500">
              {filtered.length} dari {allResults.length} hasil sesuai filter
            </p>
            <button
              onClick={() => { setSearch(""); setAlertType("ALL"); setMinProb(0); setMinRR(3); setDirection("ALL"); }}
              className="text-[10px] text-teal-400 hover:text-teal-300 underline">
              Reset semua filter
            </button>
          </div>
        )}

        {/* Empty */}
        {!loading && filtered.length === 0 && (
          <div className="text-center text-neutral-500 text-sm py-8">
            {hasFilters ? (
              <>
                <p className="text-2xl mb-2">🔍</p>
                <p>Tidak ada hasil untuk filter ini</p>
                <p className="text-[10px] mt-1 text-neutral-600">
                  {search ? `Symbol "${search}" tidak ditemukan` : "Coba longgarkan filter"}
                </p>
              </>
            ) : (
              <p>No early-warning setups found for selected style</p>
            )}
          </div>
        )}

        {/* Results grid */}
        {filtered.length > 0 && (
          <div className={fullPage ? "grid grid-cols-1 md:grid-cols-2 gap-2" : "space-y-2"}>
            {filtered.map(r => <SignalCard key={r.symbol} signal={r} />)}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
