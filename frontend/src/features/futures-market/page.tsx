"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { fmtPrice, fmtVol } from "@/lib/format";
import { PctBadge } from "@/components/ui/trading-badges";
import { type Overview, fmtChangeColor, MOOD_CFG } from "./components/types";
import { FundingBadge, CoinRow, NewListingCard, HeatTile } from "./components/CoinWidgets";
import { SentimenTab } from "./components/SentimenTab";

type TabKey = "overview" | "gainers" | "losers" | "new" | "volume" | "sentiment" | "heatmap" | "radar";

interface RadarMover {
  symbol:     string;
  change_24h: number;
  price:      number;
  funding_rate: number;
  status:     string;
  reason:     string;
  tier:       string;
  matches:    { agent: string; direction: string; score: number }[];
}

export default function FuturesMarketPage() {
  const [data,        setData]        = useState<Overview | null>(null);
  const [radarMovers, setRadarMovers] = useState<RadarMover[] | null>(null);
  const [loading,     setLoading]     = useState(true);
  const [tab,         setTab]         = useState<TabKey>("overview");
  const [countdown,   setCountdown]   = useState(60);
  const countRef = useRef(60);

  const fetchData = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    try {
      const url = forceRefresh
        ? "/api/v1/market/futures-overview?refresh=true"
        : "/api/v1/market/futures-overview";
      const r = await fetch(url);
      if (r.ok) {
        setData(await r.json() as Overview);
        countRef.current = 60;
        setCountdown(60);
      }
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  const fetchRadar = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/futures/big-movers?limit=200");
      if (r.ok) {
        const d = await r.json() as { movers: RadarMover[] };
        const preMove = (d.movers ?? []).filter(m =>
          m.tier === "coiling" || m.tier === "rising_star"
        );
        setRadarMovers(preMove);
      }
    } catch { /* silent */ }
  }, []);

  useEffect(() => { void fetchData(); }, [fetchData]);

  useEffect(() => {
    if (tab === "radar" && !radarMovers) void fetchRadar();
  }, [tab, radarMovers, fetchRadar]);

  useEffect(() => {
    const poll = setInterval(() => { void fetchData(); }, 60_000);
    const tick = setInterval(() => {
      countRef.current = Math.max(0, countRef.current - 1);
      setCountdown(countRef.current);
    }, 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [fetchData]);

  const ms      = data?.market_stats;
  const sent    = data?.sentiment;
  const upPct   = ms ? Math.round((ms.up_count / ms.total_pairs) * 100) : 50;
  const moodCfg = sent ? (MOOD_CFG[sent.market_mood] ?? MOOD_CFG["neutral"]) : null;

  const TABS: { key: TabKey; label: string; count?: number }[] = [
    { key: "overview",   label: "📊 Overview" },
    { key: "gainers",    label: "📈 Naik",      count: data?.top_gainers.length },
    { key: "losers",     label: "📉 Turun",     count: data?.top_losers.length  },
    { key: "new",        label: "🆕 New",       count: data?.new_listings.length },
    { key: "volume",     label: "💰 Volume",    count: data?.top_volume.length  },
    { key: "sentiment",  label: "📡 Sentimen"  },
    { key: "heatmap",    label: "🗺 Heatmap"   },
    { key: "radar",      label: "🔭 Pre-Move Radar", count: radarMovers?.length },
  ];

  return (
    <div className="space-y-5">

      {/* Header */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white overflow-hidden">
        <div className="p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-3 mb-1.5">
                <span className="text-3xl">⚡</span>
                <div>
                  <h1 className="text-2xl font-bold">Futures Market 24H</h1>
                  <p className="text-xs text-neutral-400">
                    Binance USDT-M Perpetual · Gainers · Losers · New Listings · Volume · Funding Rate · OI
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 items-center">
              {ms && sent && (
                <>
                  <div className="bg-green-500/20 border border-green-500/30 rounded-xl px-3 py-2 text-center">
                    <p className="text-green-400 font-black text-xl">{ms.up_count}</p>
                    <p className="text-[9px] text-green-300">📈 NAIK</p>
                  </div>
                  <div className="bg-red-500/20 border border-red-500/30 rounded-xl px-3 py-2 text-center">
                    <p className="text-red-400 font-black text-xl">{ms.down_count}</p>
                    <p className="text-[9px] text-red-300">📉 TURUN</p>
                  </div>
                  <div className="bg-teal-500/20 border border-teal-500/30 rounded-xl px-3 py-2 text-center">
                    <p className="text-teal-400 font-black text-xl">{ms.new_count}</p>
                    <p className="text-[9px] text-teal-300">🆕 BARU</p>
                  </div>
                  <div className="bg-orange-500/20 border border-orange-500/30 rounded-xl px-3 py-2 text-center">
                    <p className="text-orange-400 font-black text-xl">{ms.big_mover_count}</p>
                    <p className="text-[9px] text-orange-300">🔥 &gt;10%</p>
                  </div>
                  <div
                    className="border rounded-xl px-3 py-2 text-center cursor-pointer hover:opacity-80 transition-opacity"
                    style={{ borderColor: "rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)" }}
                    onClick={() => setTab("sentiment")}
                  >
                    <p className={`font-black text-sm ${moodCfg?.color ?? "text-neutral-300"}`}>{moodCfg?.label ?? "—"}</p>
                    <p className="text-[9px] text-neutral-400">
                      FR avg {sent.avg_funding_rate >= 0 ? "+" : ""}{sent.avg_funding_rate.toFixed(4)}%
                    </p>
                  </div>
                  <div className="bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-center">
                    <p className="text-white font-black text-xl">{ms.total_pairs}</p>
                    <p className="text-[9px] text-neutral-400">Total Pairs</p>
                  </div>
                </>
              )}
              <div className="flex items-center gap-2 flex-col">
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-blue-500/20 border border-blue-500/30">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                  <span className="text-[11px] font-bold text-blue-300">LIVE {countdown}s</span>
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
              <div className="h-3 bg-neutral-700 rounded-full overflow-hidden flex">
                <div className="bg-green-500 h-full transition-all duration-500" style={{ width: `${upPct}%` }} />
                <div className="bg-neutral-600 h-full" style={{ width: `${Math.round((ms.neutral_count / ms.total_pairs) * 100)}%` }} />
                <div className="bg-red-500 h-full" />
              </div>
              <p className="text-[9px] text-neutral-400 mt-1">
                Total volume 24H: <strong className="text-neutral-200">${fmtVol(ms.total_vol_usdt)}</strong>
                {sent && <> · Total OI (top 30): <strong className="text-purple-300">${fmtVol(sent.total_oi_usdt)}</strong></>}
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
            <span className="text-3xl animate-bounce">⚡</span>
          </div>
          <p className="font-semibold text-neutral-700">Mengambil data market Binance...</p>
          <p className="text-xs text-neutral-400 mt-1">exchangeInfo + premiumIndex + 24H ticker + OI semua pair</p>
        </div>
      )}

      {/* Overview Tab */}
      {tab === "overview" && data && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {data.big_movers.length > 0 && (
            <div className="lg:col-span-4 bg-orange-50 border border-orange-200 rounded-2xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <p className="text-sm font-bold text-orange-700">🔥 Big Movers — Pergerakan {">"} 10% dalam 24H</p>
                <span className="text-[10px] bg-orange-200 text-orange-700 px-2 py-0.5 rounded-full font-bold">{data.big_movers.length} coins</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {data.big_movers.sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct)).map(c => (
                  <div key={c.symbol} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border ${
                    c.change_pct > 0 ? "bg-green-100 border-green-300 text-green-800" : "bg-red-100 border-red-300 text-red-800"
                  }`}>
                    <span>{c.base}</span>
                    <span>{c.change_pct >= 0 ? "▲" : "▼"} {Math.abs(c.change_pct).toFixed(1)}%</span>
                    <FundingBadge fr={c.funding_rate} />
                    {c.is_new && <span className="text-[8px] bg-teal-500 text-white px-1 rounded">NEW</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {sent && moodCfg && (
            <div
              className="lg:col-span-4 bg-neutral-900 text-white rounded-2xl p-4 flex items-center gap-4 flex-wrap cursor-pointer hover:bg-neutral-800 transition-colors"
              onClick={() => setTab("sentiment")}
            >
              <div className="flex-1">
                <p className="text-xs text-neutral-400 mb-0.5">📡 Market Sentiment</p>
                <div className="flex items-center gap-3 flex-wrap">
                  <span className={`text-xl font-black ${moodCfg.color}`}>{moodCfg.label}</span>
                  <span className="text-sm text-neutral-400">{moodCfg.desc}</span>
                </div>
              </div>
              <div className="flex gap-4 text-center">
                <div><p className="text-red-400 font-black">{sent.funding_pos_count}</p><p className="text-[9px] text-neutral-400">FR+ longs</p></div>
                <div><p className="text-green-400 font-black">{sent.funding_neg_count}</p><p className="text-[9px] text-neutral-400">FR- shorts</p></div>
                <div>
                  <p className={`font-black ${sent.avg_funding_rate > 0 ? "text-red-400" : "text-green-400"}`}>
                    {sent.avg_funding_rate >= 0 ? "+" : ""}{sent.avg_funding_rate.toFixed(4)}%
                  </p>
                  <p className="text-[9px] text-neutral-400">avg FR</p>
                </div>
                <div><p className="text-purple-400 font-black">${fmtVol(sent.total_oi_usdt)}</p><p className="text-[9px] text-neutral-400">total OI</p></div>
              </div>
              <span className="text-neutral-500 text-xs">Lihat detail →</span>
            </div>
          )}

          {[
            { title: "📈 Top Gainers",       list: data.top_gainers,    tab: "gainers" as TabKey, hdr: "bg-green-50 border-green-100", ttl: "text-green-700",  link: "text-green-600"  },
            { title: "📉 Top Losers",        list: data.top_losers,     tab: "losers"  as TabKey, hdr: "bg-red-50 border-red-100",     ttl: "text-red-600",    link: "text-red-600"    },
            { title: "🆕 New Listings (30d)",list: data.new_listings,   tab: "new"     as TabKey, hdr: "bg-teal-50 border-teal-100",   ttl: "text-teal-700",   link: "text-teal-600"   },
            { title: "💰 Volume Leaders",    list: data.top_volume,     tab: "volume"  as TabKey, hdr: "bg-blue-50 border-blue-100",   ttl: "text-blue-700",   link: "text-blue-600"   },
          ].map(({ title, list, tab: t, hdr, ttl, link }) => (
            <div key={t} className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
              <div className={`px-4 py-3 border-b ${hdr} flex justify-between items-center`}>
                <p className={`text-sm font-bold ${ttl}`}>{title}</p>
                <button onClick={() => setTab(t)} className={`text-[10px] ${link} hover:underline`}>Lihat semua →</button>
              </div>
              <div>
                {list.slice(0, 5).map((c, i) => <CoinRow key={c.symbol} c={c} rank={i + 1} showNew={t === "new"} showFR />)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Gainers Tab */}
      {tab === "gainers" && data && (
        <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 bg-green-50 border-b border-green-100">
            <p className="font-bold text-green-700">📈 Top Gainers — Kenaikan Terbesar 24H</p>
            <p className="text-[10px] text-green-600 mt-0.5">Diurutkan dari % kenaikan tertinggi</p>
          </div>
          <div className="divide-y divide-neutral-100">
            {data.top_gainers.map((c, i) => (
              <div key={c.symbol} className="flex items-center gap-3 px-5 py-3 hover:bg-green-50/30">
                <span className="text-sm font-black text-neutral-300 w-6 shrink-0">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold text-base">{c.base}<span className="text-neutral-400 font-normal text-xs">/USDT</span></span>
                    {c.is_new && <span className="text-[9px] font-black bg-teal-500 text-white px-1.5 rounded-full">NEW</span>}
                    <FundingBadge fr={c.funding_rate} />
                  </div>
                  <p className="text-[10px] text-neutral-400">
                    H: ${fmtPrice(c.high_24h)} · L: ${fmtPrice(c.low_24h)} · Vol ${fmtVol(c.quote_vol_24h)}
                    {c.open_interest_usdt !== null && <> · OI ${fmtVol(c.open_interest_usdt)}</>}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-mono font-bold text-sm">${fmtPrice(c.last_price)}</p>
                  <p className={`text-lg font-black tabular-nums ${fmtChangeColor(c.change_pct)}`}>+{c.change_pct.toFixed(2)}%</p>
                  <p className="text-[10px] text-green-500">+${fmtPrice(Math.abs(c.price_change))}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Losers Tab */}
      {tab === "losers" && data && (
        <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 bg-red-50 border-b border-red-100">
            <p className="font-bold text-red-700">📉 Top Losers — Penurunan Terbesar 24H</p>
            <p className="text-[10px] text-red-500 mt-0.5">Diurutkan dari % penurunan tertinggi</p>
          </div>
          <div className="divide-y divide-neutral-100">
            {data.top_losers.map((c, i) => (
              <div key={c.symbol} className="flex items-center gap-3 px-5 py-3 hover:bg-red-50/20">
                <span className="text-sm font-black text-neutral-300 w-6 shrink-0">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold text-base">{c.base}<span className="text-neutral-400 font-normal text-xs">/USDT</span></span>
                    {c.is_new && <span className="text-[9px] font-black bg-teal-500 text-white px-1.5 rounded-full">NEW</span>}
                    <FundingBadge fr={c.funding_rate} />
                  </div>
                  <p className="text-[10px] text-neutral-400">
                    H: ${fmtPrice(c.high_24h)} · L: ${fmtPrice(c.low_24h)} · Vol ${fmtVol(c.quote_vol_24h)}
                    {c.open_interest_usdt !== null && <> · OI ${fmtVol(c.open_interest_usdt)}</>}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-mono font-bold text-sm">${fmtPrice(c.last_price)}</p>
                  <p className={`text-lg font-black tabular-nums ${fmtChangeColor(c.change_pct)}`}>{c.change_pct.toFixed(2)}%</p>
                  <p className="text-[10px] text-red-400">-${fmtPrice(Math.abs(c.price_change))}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* New Listings Tab */}
      {tab === "new" && data && (
        <div className="space-y-4">
          {data.new_listings.length === 0 ? (
            <div className="text-center py-12 text-neutral-400">
              <p className="text-3xl mb-2">📭</p>
              <p>Tidak ada listing baru dalam 30 hari</p>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <p className="text-sm font-bold text-neutral-700">🆕 New Listings Binance Futures — 30 Hari Terakhir</p>
                <span className="text-xs bg-teal-100 text-teal-700 px-2 py-0.5 rounded-full font-bold">{data.new_listings.length} contracts</span>
              </div>
              {data.new_listings.filter(c => c.days_listed !== null && c.days_listed <= 7).length > 0 && (
                <div>
                  <p className="text-xs font-bold text-teal-600 uppercase tracking-wider mb-2">🔥 Super Baru (≤7 hari)</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {data.new_listings.filter(c => c.days_listed !== null && c.days_listed <= 7).map(c => <NewListingCard key={c.symbol} c={c} />)}
                  </div>
                </div>
              )}
              {data.new_listings.filter(c => c.days_listed === null || c.days_listed > 7).length > 0 && (
                <div>
                  <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2">📋 8–30 Hari Lalu</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {data.new_listings.filter(c => c.days_listed === null || c.days_listed > 7).map(c => <NewListingCard key={c.symbol} c={c} />)}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Volume Tab */}
      {tab === "volume" && data && (
        <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
          <div className="px-5 py-3 bg-blue-50 border-b border-blue-100">
            <p className="font-bold text-blue-700">💰 Volume Leaders — Paling Aktif 24H</p>
            <p className="text-[10px] text-blue-500 mt-0.5">Diurutkan dari volume USDT tertinggi</p>
          </div>
          <div className="divide-y divide-neutral-100">
            {data.top_volume.map((c, i) => (
              <div key={c.symbol} className="flex items-center gap-3 px-5 py-3 hover:bg-blue-50/20">
                <span className="text-sm font-black text-neutral-300 w-6 shrink-0">{i + 1}</span>
                <div className="w-20 shrink-0">
                  <div className="h-1.5 bg-neutral-100 rounded-full overflow-hidden">
                    <div className="bg-blue-400 h-full rounded-full"
                      style={{ width: `${Math.min((c.quote_vol_24h / (data.top_volume[0]?.quote_vol_24h || 1)) * 100, 100)}%` }} />
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold text-base">{c.base}<span className="text-neutral-400 font-normal text-xs">/USDT</span></span>
                    {c.is_new && <span className="text-[9px] font-black bg-teal-500 text-white px-1.5 rounded-full">NEW</span>}
                    <FundingBadge fr={c.funding_rate} />
                  </div>
                  <p className="text-[10px] text-neutral-400">
                    {c.trades_24h.toLocaleString("en-US")} trades · Last ${fmtPrice(c.last_price)}
                    {c.open_interest_usdt !== null && <> · OI ${fmtVol(c.open_interest_usdt)}</>}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-bold text-sm text-blue-700">${fmtVol(c.quote_vol_24h)}</p>
                  <PctBadge pct={c.change_pct} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sentiment Tab */}
      {tab === "sentiment" && data && <SentimenTab data={data} />}

      {/* Pre-Move Radar Tab */}
      {tab === "radar" && (
        <div className="space-y-4">
          <div className="bg-gradient-to-br from-indigo-900 via-indigo-800 to-purple-900 text-white rounded-2xl p-5">
            <p className="text-xs text-indigo-300 uppercase tracking-wider font-semibold mb-1">🔭 PLAN_v3 P6 — Pre-Move Radar</p>
            <h2 className="text-xl font-black mb-1">Pre-Move Radar</h2>
            <p className="text-sm text-indigo-200">
              Koin yang <strong>belum bergerak besar</strong> tapi menunjukkan sinyal pre-breakout:
              BB Squeeze (coiling) atau kenaikan awal 6-10% dengan volume 2× (rising star).
              Ini target prioritas untuk Agent 1 (Pre-Gainer) dan Agent 2 (Accumulation).
            </p>
          </div>

          {!radarMovers ? (
            <div className="text-center py-12 text-neutral-400">
              <div className="w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
              Memuat radar data...
            </div>
          ) : radarMovers.length === 0 ? (
            <div className="text-center py-12 text-neutral-400">
              <p className="text-3xl mb-2">🔭</p>
              <p>Tidak ada koin pre-move terdeteksi saat ini.</p>
              <p className="text-xs mt-1">Data diperbarui setiap scan cycle (~2 menit).</p>
            </div>
          ) : (
            <>
              {/* Coiling section */}
              {radarMovers.filter(m => m.tier === "coiling").length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <p className="text-sm font-bold text-blue-700">🔵 Coiling — BB Squeeze Terdeteksi</p>
                    <span className="text-[10px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-bold">
                      {radarMovers.filter(m => m.tier === "coiling").length} koin
                    </span>
                  </div>
                  <div className="grid gap-2">
                    {radarMovers.filter(m => m.tier === "coiling").map(m => (
                      <div key={m.symbol} className="bg-white border border-blue-100 rounded-xl p-3 flex items-center gap-3 flex-wrap hover:border-blue-300 transition-colors">
                        <div className="flex-1 min-w-[120px]">
                          <p className="text-sm font-bold text-neutral-800">{m.symbol.replace("USDT", "")}<span className="text-neutral-400 font-normal text-xs">/USDT</span></p>
                          <p className="text-[10px] text-neutral-400">${m.price > 0 ? m.price.toPrecision(4) : "—"}</p>
                        </div>
                        <span className={`text-sm font-bold tabular-nums ${m.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
                          {m.change_24h >= 0 ? "+" : ""}{m.change_24h.toFixed(1)}%
                        </span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${m.funding_rate > 0 ? "bg-orange-50 text-orange-600" : "bg-green-50 text-green-600"}`}>
                          FR {m.funding_rate >= 0 ? "+" : ""}{(m.funding_rate * 100).toFixed(3)}%
                        </span>
                        {m.matches.length > 0 && (
                          <span className="text-[10px] bg-teal-50 text-teal-600 px-2 py-0.5 rounded-full font-semibold">
                            ✓ {m.matches[0].agent.replace("futures_", "")} {m.matches[0].direction} {m.matches[0].score}pts
                          </span>
                        )}
                        <span className="text-[9px] text-blue-500 font-semibold">🔵 coiling</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Rising star section */}
              {radarMovers.filter(m => m.tier === "rising_star").length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <p className="text-sm font-bold text-yellow-700">⭐ Rising Star — 6-10% + Volume 2×</p>
                    <span className="text-[10px] bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full font-bold">
                      {radarMovers.filter(m => m.tier === "rising_star").length} koin
                    </span>
                  </div>
                  <div className="grid gap-2">
                    {radarMovers.filter(m => m.tier === "rising_star").map(m => (
                      <div key={m.symbol} className="bg-white border border-yellow-100 rounded-xl p-3 flex items-center gap-3 flex-wrap hover:border-yellow-300 transition-colors">
                        <div className="flex-1 min-w-[120px]">
                          <p className="text-sm font-bold text-neutral-800">{m.symbol.replace("USDT", "")}<span className="text-neutral-400 font-normal text-xs">/USDT</span></p>
                          <p className="text-[10px] text-neutral-400">${m.price > 0 ? m.price.toPrecision(4) : "—"}</p>
                        </div>
                        <span className="text-sm font-bold tabular-nums text-green-600">
                          +{m.change_24h.toFixed(1)}%
                        </span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${m.funding_rate > 0 ? "bg-orange-50 text-orange-600" : "bg-green-50 text-green-600"}`}>
                          FR {m.funding_rate >= 0 ? "+" : ""}{(m.funding_rate * 100).toFixed(3)}%
                        </span>
                        {m.matches.length > 0 ? (
                          <span className="text-[10px] bg-teal-50 text-teal-600 px-2 py-0.5 rounded-full font-semibold">
                            ✓ {m.matches[0].agent.replace("futures_", "")} {m.matches[0].direction} {m.matches[0].score}pts
                          </span>
                        ) : (
                          <span className="text-[9px] text-neutral-400">{m.reason.slice(0, 40)}</span>
                        )}
                        <span className="text-[9px] text-yellow-600 font-semibold">⭐ rising_star</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Heatmap Tab */}
      {tab === "heatmap" && data && (
        <div className="space-y-4">
          <div className="bg-white border border-neutral-200 rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <div>
                <p className="font-bold text-neutral-800">🗺 Market Heatmap — 24H</p>
                <p className="text-[10px] text-neutral-400">Ukuran tile ∝ volume · Warna ∝ % perubahan · Hover untuk FR & Vol</p>
              </div>
              <div className="flex items-center gap-2 text-[10px]">
                {[
                  { cls: "bg-green-600", label: "≥15%" },
                  { cls: "bg-green-400", label: "3-15%" },
                  { cls: "bg-green-100 border", label: "0-3%" },
                  { cls: "bg-red-100 border", label: "-3-0%" },
                  { cls: "bg-red-400", label: "-3-15%" },
                  { cls: "bg-red-700", label: "≤-15%" },
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
                .slice(0, 60)
                .map(c => <HeatTile key={c.symbol} c={c} />)}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
