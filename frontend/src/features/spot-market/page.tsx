"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { fmtVol } from "@/lib/format";
import { PctBadge } from "@/components/ui/trading-badges";
import { type SpotOverview, fmtChangeColor } from "./components/types";
import { SpotCoinRow, HeatTile } from "./components/SpotCoinRow";

type TabKey = "overview" | "gainers" | "losers" | "volume" | "heatmap";

export default function SpotMarketPage() {
  const [data,      setData]      = useState<SpotOverview | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [tab,       setTab]       = useState<TabKey>("overview");
  const [countdown, setCountdown] = useState(60);
  const countRef = useRef(60);

  const fetchData = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    try {
      const url = forceRefresh
        ? "/api/v1/market/spot-overview?refresh=true"
        : "/api/v1/market/spot-overview";
      const r = await fetch(url);
      if (r.ok) {
        setData(await r.json() as SpotOverview);
        countRef.current = 60;
        setCountdown(60);
      }
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void fetchData(); }, [fetchData]);
  useEffect(() => {
    const poll = setInterval(() => { void fetchData(); }, 60_000);
    const tick = setInterval(() => {
      countRef.current = Math.max(0, countRef.current - 1);
      setCountdown(countRef.current);
    }, 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [fetchData]);

  const ms     = data?.market_stats;
  const upPct  = ms ? Math.round((ms.up_count / ms.total_pairs) * 100) : 50;

  const TABS: { key: TabKey; label: string; count?: number }[] = [
    { key: "overview", label: "📊 Overview" },
    { key: "gainers",  label: "📈 Naik",   count: data?.top_gainers.length },
    { key: "losers",   label: "📉 Turun",  count: data?.top_losers.length  },
    { key: "volume",   label: "💰 Volume", count: data?.top_volume.length  },
    { key: "heatmap",  label: "🗺 Heatmap" },
  ];

  return (
    <div className="space-y-5">

      {/* Header */}
      <div className="rounded-2xl bg-gradient-to-br from-teal-900 via-teal-800 to-neutral-900 text-white overflow-hidden">
        <div className="p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-3 mb-1.5">
                <span className="text-3xl">🎯</span>
                <div>
                  <h1 className="text-2xl font-bold">Spot Market 24H</h1>
                  <p className="text-xs text-teal-300">
                    Binance USDT Spot Pairs · Gainers · Losers · Volume Leaders · Heatmap
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 items-center">
              {ms && (
                <>
                  <div className="bg-green-500/20 border border-green-500/30 rounded-xl px-3 py-2 text-center">
                    <p className="text-green-400 font-black text-xl">{ms.up_count}</p>
                    <p className="text-[9px] text-green-300">📈 NAIK</p>
                  </div>
                  <div className="bg-red-500/20 border border-red-500/30 rounded-xl px-3 py-2 text-center">
                    <p className="text-red-400 font-black text-xl">{ms.down_count}</p>
                    <p className="text-[9px] text-red-300">📉 TURUN</p>
                  </div>
                  <div className="bg-orange-500/20 border border-orange-500/30 rounded-xl px-3 py-2 text-center">
                    <p className="text-orange-400 font-black text-xl">{ms.big_mover_count}</p>
                    <p className="text-[9px] text-orange-300">🔥 &gt;8%</p>
                  </div>
                  <div className="bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-center">
                    <p className="text-white font-black text-xl">{ms.total_pairs}</p>
                    <p className="text-[9px] text-neutral-400">Total Pairs</p>
                  </div>
                </>
              )}
              <div className="flex items-center gap-2 flex-col">
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-teal-500/20 border border-teal-500/30">
                  <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
                  <span className="text-[11px] font-bold text-teal-300">LIVE {countdown}s</span>
                </div>
                <button onClick={() => void fetchData(true)} disabled={loading}
                  className="text-xs bg-teal-600 hover:bg-teal-500 disabled:opacity-40 px-3 py-1.5 rounded-lg font-semibold transition-colors">
                  {loading ? "..." : "↺ Refresh"}
                </button>
              </div>
            </div>
          </div>

          {ms && (
            <div className="mt-4">
              <div className="flex justify-between text-[10px] mb-1">
                <span className="text-green-400 font-semibold">{ms.up_count} naik ({upPct}%)</span>
                <span className={`font-bold ${ms.avg_change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                  Avg 24H: {ms.avg_change_pct >= 0 ? "+" : ""}{ms.avg_change_pct.toFixed(2)}%
                </span>
                <span className="text-red-400 font-semibold">{ms.down_count} turun ({100 - upPct}%)</span>
              </div>
              <div className="h-3 bg-teal-900/60 rounded-full overflow-hidden flex">
                <div className="bg-green-500 h-full transition-all duration-500" style={{ width: `${upPct}%` }} />
                <div className="bg-neutral-600 h-full"
                  style={{ width: `${Math.round((ms.neutral_count / ms.total_pairs) * 100)}%` }} />
                <div className="bg-red-500 h-full" />
              </div>
              <p className="text-[9px] text-teal-300 mt-1">
                Total volume 24H: <strong className="text-white">${fmtVol(ms.total_vol_usdt)}</strong>
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-neutral-100 p-1 rounded-xl flex-wrap">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
              tab === t.key ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
            }`}>
            {t.label}
            {t.count !== undefined && (
              <span className={`text-[10px] px-1 rounded ${tab === t.key ? "bg-neutral-100" : "bg-neutral-200"}`}>
                {t.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {loading && !data && (
        <div className="py-20 text-center">
          <div className="w-14 h-14 rounded-full bg-teal-100 flex items-center justify-center mx-auto mb-3">
            <span className="text-3xl animate-bounce">🎯</span>
          </div>
          <p className="font-semibold text-neutral-700">Mengambil data spot market Binance...</p>
          <p className="text-xs text-neutral-400 mt-1">Semua USDT spot pairs · 24H ticker</p>
        </div>
      )}

      {/* Overview Tab */}
      {tab === "overview" && data && (
        <div className="space-y-4">
          {data.big_movers.length > 0 && (
            <div className="bg-orange-50 border border-orange-200 rounded-2xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <p className="text-sm font-bold text-orange-700">🔥 Big Movers — Pergerakan &gt;8% dalam 24H</p>
                <span className="text-[10px] bg-orange-200 text-orange-700 px-2 py-0.5 rounded-full font-bold">
                  {data.big_movers.length} coins
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {data.big_movers.map(c => (
                  <div key={c.symbol} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border ${
                    c.change_pct > 0
                      ? "bg-green-100 border-green-300 text-green-800"
                      : "bg-red-100 border-red-300 text-red-800"
                  }`}>
                    <span>{c.base}</span>
                    <span>{c.change_pct >= 0 ? "▲" : "▼"} {Math.abs(c.change_pct).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              { title: "📈 Top Gainers",    list: data.top_gainers, tab: "gainers" as TabKey, hdr: "bg-green-50 border-green-100", ttl: "text-green-700", link: "text-green-600" },
              { title: "📉 Top Losers",     list: data.top_losers,  tab: "losers"  as TabKey, hdr: "bg-red-50 border-red-100",     ttl: "text-red-600",   link: "text-red-600"  },
              { title: "💰 Volume Leaders", list: data.top_volume,  tab: "volume"  as TabKey, hdr: "bg-blue-50 border-blue-100",   ttl: "text-blue-700",  link: "text-blue-600" },
            ].map(({ title, list, tab: t, hdr, ttl, link }) => (
              <div key={t} className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
                <div className={`px-4 py-3 border-b ${hdr} flex justify-between items-center`}>
                  <p className={`text-sm font-bold ${ttl}`}>{title}</p>
                  <button onClick={() => setTab(t)} className={`text-[10px] ${link} hover:underline`}>
                    Lihat semua →
                  </button>
                </div>
                <div>
                  {list.slice(0, 7).map((c, i) => (
                    <div key={c.symbol} className="flex items-center gap-3 px-4 py-2.5 border-b border-neutral-50 last:border-0 hover:bg-neutral-50">
                      <span className="text-xs font-black text-neutral-300 w-5 shrink-0">{i + 1}</span>
                      <div className="flex-1 min-w-0">
                        <p className="font-bold text-sm">{c.base}<span className="text-neutral-400 font-normal text-xs">/USDT</span></p>
                        <p className="text-[10px] text-neutral-400">${fmtVol(c.quote_vol_24h)} vol</p>
                      </div>
                      <div className="text-right shrink-0">
                        <PctBadge pct={c.change_pct} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Gainers Tab */}
      {tab === "gainers" && data && (
        <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 bg-green-50 border-b border-green-100">
            <p className="font-bold text-green-700">📈 Top Gainers — Kenaikan Terbesar 24H (Spot)</p>
          </div>
          <div>
            {data.top_gainers.map((c, i) => <SpotCoinRow key={c.symbol} c={c} rank={i + 1} />)}
          </div>
        </div>
      )}

      {/* Losers Tab */}
      {tab === "losers" && data && (
        <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 bg-red-50 border-b border-red-100">
            <p className="font-bold text-red-700">📉 Top Losers — Penurunan Terbesar 24H (Spot)</p>
          </div>
          <div>
            {data.top_losers.map((c, i) => <SpotCoinRow key={c.symbol} c={c} rank={i + 1} />)}
          </div>
        </div>
      )}

      {/* Volume Tab */}
      {tab === "volume" && data && (
        <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 bg-blue-50 border-b border-blue-100">
            <p className="font-bold text-blue-700">💰 Volume Leaders — Paling Aktif 24H (Spot)</p>
          </div>
          <div>
            {data.top_volume.map((c, i) => (
              <SpotCoinRow
                key={c.symbol} c={c} rank={i + 1}
                mode="volume"
                maxVol={data.top_volume[0]?.quote_vol_24h ?? 1}
              />
            ))}
          </div>
        </div>
      )}

      {/* Heatmap Tab */}
      {tab === "heatmap" && data && (
        <div className="bg-white border border-neutral-200 rounded-2xl p-4">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <div>
              <p className="font-bold text-neutral-800">🗺 Spot Market Heatmap — 24H</p>
              <p className="text-[10px] text-neutral-400">Ukuran tile ∝ volume · Warna ∝ % perubahan</p>
            </div>
            <div className="flex items-center gap-2 text-[10px]">
              {[
                { cls: "bg-green-600", label: "≥15%" },
                { cls: "bg-green-400", label: "3-15%" },
                { cls: "bg-green-100 border", label: "0-3%" },
                { cls: "bg-red-100 border",   label: "-3-0%" },
                { cls: "bg-red-400",  label: "-3-15%" },
                { cls: "bg-red-700",  label: "≤-15%" },
              ].map(l => (
                <span key={l.label} className="flex items-center gap-1 text-neutral-500">
                  <span className={`w-3 h-3 rounded ${l.cls}`} />
                  {l.label}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {[...data.top_gainers, ...data.top_losers, ...data.top_volume]
              .filter((c, i, arr) => arr.findIndex(x => x.symbol === c.symbol) === i)
              .sort((a, b) => b.quote_vol_24h - a.quote_vol_24h)
              .slice(0, 80)
              .map(c => <HeatTile key={c.symbol} c={c} />)}
          </div>
        </div>
      )}
    </div>
  );
}
