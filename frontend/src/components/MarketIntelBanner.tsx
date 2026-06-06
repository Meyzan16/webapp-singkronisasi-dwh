"use client";
import { useCallback, useEffect, useRef, useState } from "react";

interface MarketCtx {
  sentiment:            string;
  btc_price:            number;
  btc_change_24h:       number;
  avg_change_top50:     number;
  pct_green:            number;
  pct_red:              number;
  coins_down_10pct?:    number;
  coins_up_10pct?:      number;
  btc_funding:          number;
  futures_signal_count?: number;
  opp_signal_count?:     number;
  // new field names
  futures_msg?:         string;
  opp_msg?:             string;
  // old field names (backward compat)
  futures_zero_msg?:    string;
  opp_context_msg?:     string;
  generated_at:         number;
}

const SENTIMENT_CFG: Record<string, { label: string; dot: string; strip: string; text: string }> = {
  strongly_bullish: { label: "BULLISH KUAT", dot: "bg-green-500",  strip: "bg-green-50 border-green-200",  text: "text-green-700" },
  bullish:          { label: "BULLISH",       dot: "bg-green-400",  strip: "bg-green-50 border-green-200",  text: "text-green-600" },
  neutral:          { label: "SIDEWAYS",      dot: "bg-neutral-400",strip: "bg-neutral-50 border-neutral-200", text: "text-neutral-600" },
  bearish:          { label: "BEARISH",       dot: "bg-red-500",    strip: "bg-red-50 border-red-200",      text: "text-red-600"   },
  strongly_bearish: { label: "BEARISH KUAT",  dot: "bg-red-600",    strip: "bg-red-50 border-red-300",      text: "text-red-700"   },
  unknown:          { label: "—",             dot: "bg-neutral-300",strip: "bg-neutral-50 border-neutral-200", text: "text-neutral-500" },
};

interface Props {
  mode: "futures" | "spot";
  refreshMs?: number;
}

export function MarketIntelBanner({ mode, refreshMs = 60_000 }: Props) {
  const [ctx, setCtx]         = useState<MarketCtx | null>(null);
  const [loading, setLoading] = useState(true);
  const timerRef              = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchCtx = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/market/context");
      if (r.ok) setCtx(await r.json() as MarketCtx);
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void fetchCtx();
    timerRef.current = setInterval(() => void fetchCtx(), refreshMs);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [fetchCtx, refreshMs]);

  if (loading) return (
    <div className="rounded-xl border border-neutral-200 bg-neutral-50 px-4 py-2.5 animate-pulse h-10" />
  );
  if (!ctx) return null;

  const cfg      = SENTIMENT_CFG[ctx.sentiment] ?? SENTIMENT_CFG.unknown;
  const btcUp    = ctx.btc_change_24h >= 0;
  const avgUp    = ctx.avg_change_top50 >= 0;
  const frAbs    = Math.abs(ctx.btc_funding);
  const frHot    = frAbs > 0.05;

  // Safe count handling — -1 = not yet scanned, undefined = API field missing
  const futCount = typeof ctx.futures_signal_count === "number" ? ctx.futures_signal_count : -1;
  const oppCount = typeof ctx.opp_signal_count      === "number" ? ctx.opp_signal_count      : -1;

  // Support both new and old field names
  const contextMsg = mode === "futures"
    ? (ctx.futures_msg || ctx.futures_zero_msg || "")
    : (ctx.opp_msg     || ctx.opp_context_msg  || "");

  return (
    <div className={`rounded-xl border ${cfg.strip} text-sm`}>

      {/* ── Row 1: BTC + Sentiment + key stats ────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">

        {/* Sentiment */}
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`w-2 h-2 rounded-full ${cfg.dot} shrink-0`} />
          <span className={`text-xs font-black ${cfg.text}`}>{cfg.label}</span>
        </div>

        <span className="text-neutral-300 text-xs">|</span>

        {/* BTC */}
        <span className="text-xs text-neutral-700 font-semibold tabular-nums shrink-0">
          BTC{" "}
          <span className="font-black text-neutral-900">${ctx.btc_price.toLocaleString()}</span>{" "}
          <span className={btcUp ? "text-green-600" : "text-red-500"}>
            ({btcUp ? "+" : ""}{ctx.btc_change_24h.toFixed(1)}%)
          </span>
        </span>

        <span className="text-neutral-300 text-xs">|</span>

        {/* % merah */}
        <span className={`text-xs font-semibold shrink-0 ${ctx.pct_red > 60 ? "text-red-600" : ctx.pct_green > 60 ? "text-green-600" : "text-neutral-600"}`}>
          {ctx.pct_red.toFixed(0)}% merah
        </span>

        {/* Avg */}
        <span className={`text-xs font-semibold shrink-0 ${avgUp ? "text-green-600" : "text-red-500"}`}>
          Avg {avgUp ? "+" : ""}{ctx.avg_change_top50.toFixed(1)}%
        </span>

        {/* Big movers */}
        {(ctx.coins_down_10pct ?? 0) > 0 && (
          <span className="text-xs font-semibold text-orange-600 shrink-0">
            ⚠ {ctx.coins_down_10pct} koin &minus;10%
          </span>
        )}
        {(ctx.coins_up_10pct ?? 0) > 0 && (
          <span className="text-xs font-semibold text-green-600 shrink-0">
            ↑ {ctx.coins_up_10pct} koin +10%
          </span>
        )}

        {/* Funding */}
        <span className={`text-xs font-semibold shrink-0 ${frHot ? (ctx.btc_funding > 0 ? "text-red-600" : "text-green-600") : "text-neutral-500"}`}>
          F {ctx.btc_funding >= 0 ? "+" : ""}{ctx.btc_funding.toFixed(3)}%{frHot ? " 🔥" : ""}
        </span>
      </div>

      {/* ── Row 2: Signal counts ─────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 border-t border-neutral-200/60">

        {/* Futures count */}
        <span className="text-xs shrink-0 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
          <span className="font-semibold text-neutral-500">Futures:</span>{" "}
          <span className={`font-black ${futCount > 0 ? "text-blue-600" : "text-neutral-400"}`}>
            {futCount < 0 ? "belum scan" : futCount === 0 ? "0 sinyal" : `${futCount} sinyal`}
          </span>
        </span>

        <span className="text-neutral-300 text-xs hidden sm:inline">·</span>

        {/* Spot opp count */}
        <span className="text-xs shrink-0 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-teal-400 shrink-0" />
          <span className="font-semibold text-neutral-500">Spot Opp:</span>{" "}
          <span className={`font-black ${oppCount > 0 ? "text-teal-600" : "text-neutral-400"}`}>
            {oppCount < 0 ? "belum scan" : oppCount === 0 ? "0 rekomendasi" : `${oppCount} rekomendasi`}
          </span>
        </span>
      </div>

      {/* ── Row 3: Context message — always visible ───────────────────────── */}
      {contextMsg && (
        <div className={`px-4 pb-3 border-t border-neutral-200/40`}>
          <p className={`text-xs leading-relaxed mt-2 ${cfg.text}`}>
            <span className="font-black mr-1">→</span>
            {contextMsg}
          </p>
        </div>
      )}
    </div>
  );
}
