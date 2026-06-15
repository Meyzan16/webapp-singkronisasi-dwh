"use client";
import { useEffect, useState } from "react";
import { fmtPrice, fmtVol } from "@/lib/format";
import { PctBadge } from "@/components/ui/trading-badges";
import { type Overview, MOOD_CFG } from "./types";
import { FundingBadge } from "./CoinWidgets";

export function SentimenTab({ data }: { data: Overview }) {
  const s   = data.sentiment;
  const cfg = MOOD_CFG[s.market_mood] ?? MOOD_CFG["neutral"];
  const total  = s.funding_pos_count + s.funding_neg_count + s.funding_neu_count;
  const posPct = total ? Math.round((s.funding_pos_count / total) * 100) : 0;
  const negPct = total ? Math.round((s.funding_neg_count / total) * 100) : 0;

  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  const nextFundingMs = data.top_gainers[0]?.next_funding_time ?? 0;
  const minsToNext    = nextFundingMs ? Math.max(0, Math.round((nextFundingMs - nowMs) / 60_000)) : null;

  return (
    <div className="space-y-5">

      {/* Mood card */}
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

      {/* Funding Rate Extremes */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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

      {/* Open Interest Leaders */}
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
