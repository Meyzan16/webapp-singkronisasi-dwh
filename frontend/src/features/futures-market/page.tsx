"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { fmtPrice, fmtVol } from "@/lib/format";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Coin {
  symbol:             string;
  base:               string;
  last_price:         number;
  mark_price:         number;
  price_change:       number;
  change_pct:         number;
  high_24h:           number;
  low_24h:            number;
  volume_24h:         number;
  quote_vol_24h:      number;
  trades_24h:         number;
  is_new:             boolean;
  onboard_date:       number | null;
  days_listed:        number | null;
  // on-chain futures
  funding_rate:       number;        // % e.g. 0.01 = 0.01%
  next_funding_time:  number;
  open_interest:      number | null;
  open_interest_usdt: number | null;
  agent1_score?:      number | null; // F98: pre-gainer scout score (if scanned)
}

interface MarketStats {
  total_pairs:      number;
  up_count:         number;
  down_count:       number;
  neutral_count:    number;
  avg_change_pct:   number;
  total_vol_usdt:   number;
  new_count:        number;
  big_mover_count:  number;
}

interface Sentiment {
  avg_funding_rate:  number;
  funding_pos_count: number;
  funding_neg_count: number;
  funding_neu_count: number;
  market_mood:       string;
  total_oi_usdt:     number;
}

interface Overview {
  new_listings:      Coin[];
  top_gainers:       Coin[];
  top_losers:        Coin[];
  top_volume:        Coin[];
  big_movers:        Coin[];
  top_funding_long:  Coin[];
  top_funding_short: Coin[];
  top_oi:            Coin[];
  market_stats:      MarketStats;
  sentiment:         Sentiment;
  generated_at:      number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtChangeColor(pct: number): string {
  if (pct >= 10)  return "text-green-600 font-black";
  if (pct >= 3)   return "text-green-500 font-bold";
  if (pct >= 0)   return "text-green-400";
  if (pct >= -3)  return "text-red-400";
  if (pct >= -10) return "text-red-500 font-bold";
  return "text-red-600 font-black";
}

function fmtBg(pct: number): string {
  if (pct >= 15)  return "bg-green-600 text-white";
  if (pct >= 8)   return "bg-green-500 text-white";
  if (pct >= 3)   return "bg-green-400 text-white";
  if (pct >= 0)   return "bg-green-100 text-green-800";
  if (pct >= -3)  return "bg-red-100 text-red-700";
  if (pct >= -8)  return "bg-red-400 text-white";
  if (pct >= -15) return "bg-red-500 text-white";
  return "bg-red-700 text-white";
}

function fmtDate(ms: number | null): string {
  if (!ms) return "—";
  return new Date(ms).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
}

function fmtFundingColor(fr: number): string {
  if (fr > 0.05)  return "bg-red-600 text-white";
  if (fr > 0.02)  return "bg-red-400 text-white";
  if (fr > 0)     return "bg-red-100 text-red-700";
  if (fr === 0)   return "bg-neutral-100 text-neutral-500";
  if (fr >= -0.02) return "bg-green-100 text-green-700";
  return "bg-green-400 text-white";
}

// Mood config
const MOOD_CFG: Record<string, { label: string; color: string; desc: string; gauge: number }> = {
  extreme_greed: { label: "Extreme Greed",  color: "text-red-600",    desc: "Longs sangat overloaded — potensi reversal tinggi",      gauge: 90 },
  greed:         { label: "Greedy",          color: "text-orange-500", desc: "Longs mendominasi — hati-hati long squeeze",             gauge: 70 },
  bullish:       { label: "Bullish",         color: "text-yellow-500", desc: "Bias bullish tipis — longs sedikit mendominasi",         gauge: 60 },
  neutral:       { label: "Neutral",         color: "text-neutral-400",desc: "Pasar seimbang — tidak ada bias kuat",                   gauge: 50 },
  bearish:       { label: "Bearish",         color: "text-teal-500",   desc: "Shorts mendominasi — bias bearish tipis",               gauge: 40 },
  fear:          { label: "Fear",            color: "text-blue-500",   desc: "Shorts overloaded — potensi short squeeze",              gauge: 20 },
};

// ── Sub-components ────────────────────────────────────────────────────────────

function PctBadge({ pct }: { pct: number }) {
  return (
    <span className={`text-xs font-black tabular-nums px-1.5 py-0.5 rounded ${
      pct > 0 ? "bg-green-100 text-green-700" : pct < 0 ? "bg-red-100 text-red-600" : "bg-neutral-100 text-neutral-500"
    }`}>
      {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
    </span>
  );
}

function FundingBadge({ fr }: { fr: number }) {
  const sign = fr > 0 ? "+" : "";
  return (
    <span className={`text-[9px] font-black tabular-nums px-1 py-0.5 rounded ${fmtFundingColor(fr)}`}
      title={`Funding Rate: ${sign}${fr.toFixed(4)}%`}>
      FR {sign}{fr.toFixed(3)}%
    </span>
  );
}

function CoinRow({ c, rank, showNew, showFR }: { c: Coin; rank: number; showNew?: boolean; showFR?: boolean }) {
  const router = useRouter();
  return (
    <div
      onClick={() => router.push(`/scanner?symbol=${c.base}`)}   // F99: jump to scanner
      title={`Scan ${c.base} di Pre-Gainer Scanner`}
      className="flex items-center gap-2 px-3 py-2 hover:bg-neutral-50 border-b border-neutral-100 last:border-0 cursor-pointer">
      <span className="text-[10px] text-neutral-400 w-5 shrink-0 tabular-nums">{rank}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-bold text-sm">{c.base}</span>
          <span className="text-[9px] text-neutral-400">/USDT</span>
          {showNew && c.is_new && (
            <span className="text-[8px] font-black bg-teal-500 text-white px-1 rounded">NEW</span>
          )}
          {showFR && <FundingBadge fr={c.funding_rate} />}
          {c.agent1_score != null && c.agent1_score >= 52 && (   // F98: pre-gainer link
            <span className="text-[8px] font-black bg-blue-100 text-blue-700 px-1 rounded" title="Skor Agent 1 Pre-Gainer">
              🎯 {c.agent1_score.toFixed(0)}
            </span>
          )}
        </div>
        <p className="text-[9px] text-neutral-400 tabular-nums">
          Vol ${fmtVol(c.quote_vol_24h)} · {c.trades_24h.toLocaleString("en-US")} trades
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-xs font-mono font-bold">${fmtPrice(c.last_price)}</p>
        <PctBadge pct={c.change_pct} />
      </div>
    </div>
  );
}

function NewListingCard({ c }: { c: Coin }) {
  const age = c.days_listed !== null ? (c.days_listed === 0 ? "Hari ini!" : `${c.days_listed} hari lalu`) : "—";
  const isVeryNew = c.days_listed !== null && c.days_listed <= 7;
  return (
    <div className={`rounded-xl border p-3 hover:shadow-md transition-all ${
      isVeryNew ? "border-teal-300 bg-teal-50" : "border-neutral-200 bg-white"
    }`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className="flex items-center gap-1.5">
            <span className="font-bold text-base">{c.base}</span>
            <span className="text-[9px] text-neutral-400">/USDT PERP</span>
            {isVeryNew && (
              <span className="text-[9px] font-black bg-teal-500 text-white px-1.5 py-0.5 rounded-full animate-pulse">🆕 BARU</span>
            )}
          </div>
          <p className="text-[10px] text-neutral-400 mt-0.5">Listed: {fmtDate(c.onboard_date)} · {age}</p>
        </div>
        <PctBadge pct={c.change_pct} />
      </div>
      <div className="grid grid-cols-3 gap-1.5 text-center mb-2">
        <div className="bg-white/80 rounded-lg px-2 py-1">
          <p className="text-[9px] text-neutral-400">Harga</p>
          <p className="text-[11px] font-mono font-bold">${fmtPrice(c.last_price)}</p>
        </div>
        <div className="bg-white/80 rounded-lg px-2 py-1">
          <p className="text-[9px] text-neutral-400">High 24H</p>
          <p className="text-[11px] font-mono font-bold text-green-600">${fmtPrice(c.high_24h)}</p>
        </div>
        <div className="bg-white/80 rounded-lg px-2 py-1">
          <p className="text-[9px] text-neutral-400">Vol USDT</p>
          <p className="text-[11px] font-mono font-bold">${fmtVol(c.quote_vol_24h)}</p>
        </div>
      </div>
      <div className="flex justify-center">
        <FundingBadge fr={c.funding_rate} />
      </div>
    </div>
  );
}

function HeatTile({ c }: { c: Coin }) {
  const router = useRouter();
  const size = Math.min(Math.max(c.quote_vol_24h / 50_000_000, 0.5), 3.0);
  return (
    <div
      onClick={() => router.push(`/scanner?symbol=${c.base}`)}   // F99: jump to scanner
      title={`${c.symbol}: ${c.change_pct >= 0 ? "+" : ""}${c.change_pct.toFixed(2)}% | Vol $${fmtVol(c.quote_vol_24h)} | FR ${c.funding_rate >= 0 ? "+" : ""}${c.funding_rate.toFixed(3)}% — klik untuk scan`}
      className={`rounded-lg flex flex-col items-center justify-center cursor-pointer transition-all hover:scale-105 ${fmtBg(c.change_pct)}`}
      style={{ padding: `${6 * size}px ${4 * size}px`, minHeight: `${36 * size}px` }}
    >
      <p className={`font-bold leading-tight ${size > 1.5 ? "text-sm" : "text-[10px]"}`}>{c.base}</p>
      <p className={`font-black tabular-nums ${size > 1.5 ? "text-base" : "text-[10px]"}`}>
        {c.change_pct >= 0 ? "+" : ""}{c.change_pct.toFixed(1)}%
      </p>
    </div>
  );
}

// ── Sentimen Tab ──────────────────────────────────────────────────────────────

function SentimenTab({ data }: { data: Overview }) {
  const s   = data.sentiment;
  const cfg = MOOD_CFG[s.market_mood] ?? MOOD_CFG["neutral"];
  const total = s.funding_pos_count + s.funding_neg_count + s.funding_neu_count;
  const posPct = total ? Math.round((s.funding_pos_count / total) * 100) : 0;
  const negPct = total ? Math.round((s.funding_neg_count / total) * 100) : 0;

  // Date.now() is impure in render — seed via lazy init, refresh from the clock in an effect
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  const nextFundingMs = data.top_gainers[0]?.next_funding_time ?? 0;
  const minsToNext    = nextFundingMs ? Math.max(0, Math.round((nextFundingMs - nowMs) / 60_000)) : null;

  return (
    <div className="space-y-5">

      {/* ── Mood card ──────────────────────────────────────────────────────── */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 to-neutral-800 text-white p-5">
        <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
          <div>
            <p className="text-xs text-neutral-400 uppercase tracking-widest mb-1">Market Sentiment</p>
            <p className={`text-3xl font-black ${cfg.color}`}>{cfg.label}</p>
            <p className="text-sm text-neutral-300 mt-1">{cfg.desc}</p>
          </div>
          <div className="text-right">
            <p className="text-xs text-neutral-400">Avg Funding Rate</p>
            <p className={`text-2xl font-black tabular-nums ${s.avg_funding_rate > 0 ? "text-red-400" : s.avg_funding_rate < 0 ? "text-green-400" : "text-neutral-300"}`}>
              {s.avg_funding_rate >= 0 ? "+" : ""}{s.avg_funding_rate.toFixed(4)}%
            </p>
            <p className="text-[10px] text-neutral-500">per 8 jam</p>
            {minsToNext !== null && (
              <p className="text-[10px] text-yellow-400 mt-1">⏱ Funding berikutnya ~{minsToNext} menit</p>
            )}
          </div>
        </div>

        {/* Gauge bar */}
        <div className="mb-3">
          <div className="relative h-4 bg-neutral-700 rounded-full overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-r from-blue-500 via-neutral-500 via-yellow-400 to-red-600 opacity-30 rounded-full" />
            <div
              className="absolute top-1 w-2 h-2 rounded-full bg-white shadow-lg transition-all duration-700"
              style={{ left: `calc(${cfg.gauge}% - 4px)` }}
            />
          </div>
          <div className="flex justify-between text-[9px] text-neutral-500 mt-1">
            <span>😨 Fear (shorts overload)</span>
            <span>Neutral</span>
            <span>😈 Greed (longs overload)</span>
          </div>
        </div>

        {/* Funding breadth */}
        <div className="grid grid-cols-3 gap-3 mt-3">
          <div className="bg-red-500/20 border border-red-500/30 rounded-xl p-3 text-center">
            <p className="text-red-400 font-black text-xl">{s.funding_pos_count}</p>
            <p className="text-[9px] text-red-300">FR Positif</p>
            <p className="text-[9px] text-red-400 font-bold">{posPct}%</p>
            <p className="text-[8px] text-neutral-400">longs bayar</p>
          </div>
          <div className="bg-white/5 border border-white/10 rounded-xl p-3 text-center">
            <p className="text-neutral-300 font-black text-xl">{s.funding_neu_count}</p>
            <p className="text-[9px] text-neutral-400">FR Netral</p>
            <p className="text-[9px] text-neutral-400 font-bold">{100 - posPct - negPct}%</p>
            <p className="text-[8px] text-neutral-500">≈ 0%</p>
          </div>
          <div className="bg-green-500/20 border border-green-500/30 rounded-xl p-3 text-center">
            <p className="text-green-400 font-black text-xl">{s.funding_neg_count}</p>
            <p className="text-[9px] text-green-300">FR Negatif</p>
            <p className="text-[9px] text-green-400 font-bold">{negPct}%</p>
            <p className="text-[8px] text-neutral-400">shorts bayar</p>
          </div>
        </div>
      </div>

      {/* ── Funding Rate Extremes ──────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* Crowded Longs */}
        <div className="bg-white border border-red-200 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 bg-red-50 border-b border-red-100">
            <p className="font-bold text-red-700 text-sm">🔴 Crowded Longs — FR Tertinggi</p>
            <p className="text-[10px] text-red-400 mt-0.5">Longs bayar shorts → potensi long squeeze jika dump</p>
          </div>
          <div className="divide-y divide-neutral-100">
            {data.top_funding_long.map((c, i) => (
              <div key={c.symbol} className="flex items-center gap-3 px-4 py-2.5 hover:bg-red-50/30">
                <span className="text-xs font-black text-neutral-300 w-5 shrink-0">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-sm">{c.base}</span>
                    <span className="text-[9px] text-neutral-400">/USDT</span>
                    {c.is_new && <span className="text-[8px] bg-teal-500 text-white px-1 rounded font-bold">NEW</span>}
                  </div>
                  <p className="text-[9px] text-neutral-400">${fmtPrice(c.last_price)} · Vol ${fmtVol(c.quote_vol_24h)}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-sm font-black text-red-600 tabular-nums">+{c.funding_rate.toFixed(4)}%</p>
                  <PctBadge pct={c.change_pct} />
                </div>
              </div>
            ))}
            {data.top_funding_long.length === 0 && (
              <p className="text-center text-neutral-400 text-xs py-6">Tidak ada funding positif signifikan</p>
            )}
          </div>
        </div>

        {/* Crowded Shorts */}
        <div className="bg-white border border-green-200 rounded-2xl overflow-hidden">
          <div className="px-4 py-3 bg-green-50 border-b border-green-100">
            <p className="font-bold text-green-700 text-sm">🟢 Crowded Shorts — FR Terendah</p>
            <p className="text-[10px] text-green-500 mt-0.5">Shorts bayar longs → potensi short squeeze jika pump</p>
          </div>
          <div className="divide-y divide-neutral-100">
            {data.top_funding_short.map((c, i) => (
              <div key={c.symbol} className="flex items-center gap-3 px-4 py-2.5 hover:bg-green-50/30">
                <span className="text-xs font-black text-neutral-300 w-5 shrink-0">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-sm">{c.base}</span>
                    <span className="text-[9px] text-neutral-400">/USDT</span>
                    {c.is_new && <span className="text-[8px] bg-teal-500 text-white px-1 rounded font-bold">NEW</span>}
                  </div>
                  <p className="text-[9px] text-neutral-400">${fmtPrice(c.last_price)} · Vol ${fmtVol(c.quote_vol_24h)}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-sm font-black text-green-600 tabular-nums">{c.funding_rate.toFixed(4)}%</p>
                  <PctBadge pct={c.change_pct} />
                </div>
              </div>
            ))}
            {data.top_funding_short.length === 0 && (
              <p className="text-center text-neutral-400 text-xs py-6">Tidak ada funding negatif signifikan</p>
            )}
          </div>
        </div>
      </div>

      {/* ── Open Interest Leaders ──────────────────────────────────────────── */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 bg-purple-50 border-b border-purple-100 flex items-center justify-between flex-wrap gap-2">
          <div>
            <p className="font-bold text-purple-700 text-sm">📊 Open Interest Leaders — Top 30</p>
            <p className="text-[10px] text-purple-400 mt-0.5">
              Total OI (top 30): <strong className="text-purple-600">${fmtVol(s.total_oi_usdt)}</strong>
            </p>
          </div>
          <p className="text-[10px] text-neutral-400">OI besar + price naik = konfirmasi trend kuat</p>
        </div>
        <div className="divide-y divide-neutral-100">
          {data.top_oi.map((c, i) => {
            const oiUsdt   = c.open_interest_usdt ?? 0;
            const maxOi    = data.top_oi[0]?.open_interest_usdt ?? 1;
            const barWidth = Math.min((oiUsdt / maxOi) * 100, 100);
            return (
              <div key={c.symbol} className="flex items-center gap-3 px-5 py-2.5 hover:bg-purple-50/20">
                <span className="text-xs font-black text-neutral-300 w-6 shrink-0">{i + 1}</span>
                {/* OI bar */}
                <div className="w-16 shrink-0">
                  <div className="h-1.5 bg-neutral-100 rounded-full overflow-hidden">
                    <div className="bg-purple-400 h-full rounded-full" style={{ width: `${barWidth}%` }} />
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-sm">{c.base}</span>
                    <span className="text-[9px] text-neutral-400">/USDT</span>
                    <FundingBadge fr={c.funding_rate} />
                  </div>
                  <p className="text-[9px] text-neutral-400">
                    ${fmtPrice(c.last_price)} · Vol ${fmtVol(c.quote_vol_24h)}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-bold text-sm text-purple-700">${fmtVol(oiUsdt)}</p>
                  <PctBadge pct={c.change_pct} />
                </div>
              </div>
            );
          })}
          {data.top_oi.length === 0 && (
            <p className="text-center text-neutral-400 text-xs py-8">Data OI tidak tersedia</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type TabKey = "overview" | "gainers" | "losers" | "new" | "volume" | "sentiment" | "heatmap";

export default function FuturesMarketPage() {
  const [data,      setData]      = useState<Overview | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [tab,       setTab]       = useState<TabKey>("overview");
  const [countdown, setCountdown] = useState(60);
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
  const sent   = data?.sentiment;
  const upPct  = ms ? Math.round((ms.up_count / ms.total_pairs) * 100) : 50;
  const moodCfg = sent ? (MOOD_CFG[sent.market_mood] ?? MOOD_CFG["neutral"]) : null;

  const TABS: { key: TabKey; label: string; count?: number }[] = [
    { key: "overview",   label: "📊 Overview" },
    { key: "gainers",    label: "📈 Naik",      count: data?.top_gainers.length },
    { key: "losers",     label: "📉 Turun",     count: data?.top_losers.length  },
    { key: "new",        label: "🆕 New",       count: data?.new_listings.length },
    { key: "volume",     label: "💰 Volume",    count: data?.top_volume.length  },
    { key: "sentiment",  label: "📡 Sentimen"  },
    { key: "heatmap",    label: "🗺 Heatmap"   },
  ];

  return (
    <div className="space-y-5">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
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

            {/* Stats pills */}
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
                  {/* Sentiment pill */}
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

          {/* Market breadth bar */}
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

      {/* ── Tab bar ─────────────────────────────────────────────────────────── */}
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

      {/* ── Loading ─────────────────────────────────────────────────────────── */}
      {loading && !data && (
        <div className="py-20 text-center">
          <div className="w-14 h-14 rounded-full bg-teal-100 flex items-center justify-center mx-auto mb-3">
            <span className="text-3xl animate-bounce">⚡</span>
          </div>
          <p className="font-semibold text-neutral-700">Mengambil data market Binance...</p>
          <p className="text-xs text-neutral-400 mt-1">exchangeInfo + premiumIndex + 24H ticker + OI semua pair</p>
        </div>
      )}

      {/* ── Overview Tab ────────────────────────────────────────────────────── */}
      {tab === "overview" && data && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">

          {/* Big Movers Alert */}
          {data.big_movers.length > 0 && (
            <div className="lg:col-span-4 bg-orange-50 border border-orange-200 rounded-2xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <p className="text-sm font-bold text-orange-700">🔥 Big Movers — Pergerakan {">"} 10% dalam 24H</p>
                <span className="text-[10px] bg-orange-200 text-orange-700 px-2 py-0.5 rounded-full font-bold">{data.big_movers.length} coins</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {data.big_movers.sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct)).map(c => (
                  <div key={c.symbol} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border ${
                    c.change_pct > 0
                      ? "bg-green-100 border-green-300 text-green-800"
                      : "bg-red-100 border-red-300 text-red-800"
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

          {/* Sentiment mini card */}
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
                <div>
                  <p className="text-red-400 font-black">{sent.funding_pos_count}</p>
                  <p className="text-[9px] text-neutral-400">FR+ longs</p>
                </div>
                <div>
                  <p className="text-green-400 font-black">{sent.funding_neg_count}</p>
                  <p className="text-[9px] text-neutral-400">FR- shorts</p>
                </div>
                <div>
                  <p className={`font-black ${sent.avg_funding_rate > 0 ? "text-red-400" : "text-green-400"}`}>
                    {sent.avg_funding_rate >= 0 ? "+" : ""}{sent.avg_funding_rate.toFixed(4)}%
                  </p>
                  <p className="text-[9px] text-neutral-400">avg FR</p>
                </div>
                <div>
                  <p className="text-purple-400 font-black">${fmtVol(sent.total_oi_usdt)}</p>
                  <p className="text-[9px] text-neutral-400">total OI</p>
                </div>
              </div>
              <span className="text-neutral-500 text-xs">Lihat detail →</span>
            </div>
          )}

          {/* Top Gainers preview */}
          <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
            <div className="px-4 py-3 bg-green-50 border-b border-green-100 flex justify-between items-center">
              <p className="text-sm font-bold text-green-700">📈 Top Gainers</p>
              <button onClick={() => setTab("gainers")} className="text-[10px] text-green-600 hover:underline">Lihat semua →</button>
            </div>
            <div>
              {data.top_gainers.slice(0, 5).map((c, i) => <CoinRow key={c.symbol} c={c} rank={i + 1} showFR />)}
            </div>
          </div>

          {/* Top Losers preview */}
          <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
            <div className="px-4 py-3 bg-red-50 border-b border-red-100 flex justify-between items-center">
              <p className="text-sm font-bold text-red-600">📉 Top Losers</p>
              <button onClick={() => setTab("losers")} className="text-[10px] text-red-600 hover:underline">Lihat semua →</button>
            </div>
            <div>
              {data.top_losers.slice(0, 5).map((c, i) => <CoinRow key={c.symbol} c={c} rank={i + 1} showFR />)}
            </div>
          </div>

          {/* New Listings preview */}
          <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
            <div className="px-4 py-3 bg-teal-50 border-b border-teal-100 flex justify-between items-center">
              <p className="text-sm font-bold text-teal-700">🆕 New Listings (30d)</p>
              <button onClick={() => setTab("new")} className="text-[10px] text-teal-600 hover:underline">Lihat semua →</button>
            </div>
            <div>
              {data.new_listings.slice(0, 5).map((c, i) => <CoinRow key={c.symbol} c={c} rank={i + 1} showNew showFR />)}
            </div>
          </div>

          {/* Volume Leaders preview */}
          <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
            <div className="px-4 py-3 bg-blue-50 border-b border-blue-100 flex justify-between items-center">
              <p className="text-sm font-bold text-blue-700">💰 Volume Leaders</p>
              <button onClick={() => setTab("volume")} className="text-[10px] text-blue-600 hover:underline">Lihat semua →</button>
            </div>
            <div>
              {data.top_volume.slice(0, 5).map((c, i) => <CoinRow key={c.symbol} c={c} rank={i + 1} showFR />)}
            </div>
          </div>
        </div>
      )}

      {/* ── Gainers Tab ─────────────────────────────────────────────────────── */}
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
                  <p className={`text-lg font-black tabular-nums ${fmtChangeColor(c.change_pct)}`}>
                    +{c.change_pct.toFixed(2)}%
                  </p>
                  <p className="text-[10px] text-green-500">+${fmtPrice(Math.abs(c.price_change))}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Losers Tab ──────────────────────────────────────────────────────── */}
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
                  <p className={`text-lg font-black tabular-nums ${fmtChangeColor(c.change_pct)}`}>
                    {c.change_pct.toFixed(2)}%
                  </p>
                  <p className="text-[10px] text-red-400">-${fmtPrice(Math.abs(c.price_change))}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── New Listings Tab ────────────────────────────────────────────────── */}
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
                    {data.new_listings.filter(c => c.days_listed !== null && c.days_listed <= 7)
                      .map(c => <NewListingCard key={c.symbol} c={c} />)}
                  </div>
                </div>
              )}
              {data.new_listings.filter(c => c.days_listed === null || c.days_listed > 7).length > 0 && (
                <div>
                  <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2">📋 8–30 Hari Lalu</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {data.new_listings.filter(c => c.days_listed === null || c.days_listed > 7)
                      .map(c => <NewListingCard key={c.symbol} c={c} />)}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── Volume Tab ──────────────────────────────────────────────────────── */}
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

      {/* ── Sentimen Tab ────────────────────────────────────────────────────── */}
      {tab === "sentiment" && data && <SentimenTab data={data} />}

      {/* ── Heatmap Tab ─────────────────────────────────────────────────────── */}
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
