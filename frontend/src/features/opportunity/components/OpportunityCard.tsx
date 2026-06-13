"use client";
import { fmtPrice } from "@/lib/format";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface OpportunityResult {
  symbol:            string;
  current_price:     number;
  opportunity_score: number;
  signals:           string[];
  alert_type:        string;
  change_24h:        number;
  change_1h:         number;
  vol_ratio:         number;
  bb_width_15m:      number | null;
  rsi_1h:            number | null;
  tfs_confirmed:     string[];
  squeeze_tfs:       string[];
  // Trade levels — exist in scanner cache but intentionally NOT shown on cards
  // They are revealed only inside CoinModal after Layer 2 analyzer runs
  entry?:    number;
  sl?:       number;
  tp1?:      number;
  tp2?:      number;
  tp3?:      number;
  risk_pct?: number;
  tp1_pct?:  number;
  tp2_pct?:  number;
  tp3_pct?:  number;
  rr_ratio?: number;
  // Risk-adjusted metrics (§11.3) + transparansi agent (§11.5)
  tp2_net_pct?:        number;
  ev_per_risk?:        number;
  raw_score?:          number;
  auto_open?:          boolean;
  weight_applied?:     number;
  direction_confirmed?: boolean;
  banned_by_learning?: boolean;
}

// ── Score helpers ─────────────────────────────────────────────────────────────

export function scoreLabel(s: number) {
  if (s >= 70) return {
    emoji: "🔥", text: "HIGH",
    ring:  "ring-green-400",
    bg:    "bg-green-500",
    txt:   "text-green-600",
    badge: "bg-green-50 text-green-700 border-green-200",
    bar:   "bg-green-500",
  };
  if (s >= 50) return {
    emoji: "⚡", text: "WATCH",
    ring:  "ring-yellow-400",
    bg:    "bg-yellow-500",
    txt:   "text-yellow-600",
    badge: "bg-yellow-50 text-yellow-700 border-yellow-200",
    bar:   "bg-yellow-400",
  };
  return {
    emoji: "👀", text: "EARLY",
    ring:  "ring-neutral-300",
    bg:    "bg-neutral-400",
    txt:   "text-neutral-500",
    badge: "bg-neutral-50 text-neutral-600 border-neutral-200",
    bar:   "bg-neutral-400",
  };
}

export const TYPE_META: Record<string, { label: string; bg: string; dot: string }> = {
  squeeze:      { label: "⚡ Squeeze",   bg: "bg-purple-100 text-purple-700 border-purple-200", dot: "bg-purple-500" },
  accumulation: { label: "📦 Akumulasi", bg: "bg-teal-100 text-teal-700 border-teal-200",       dot: "bg-teal-500"   },
  breakout:     { label: "🎯 Breakout",  bg: "bg-amber-100 text-amber-700 border-amber-200",    dot: "bg-amber-500"  },
};

// ── RSI zone label ────────────────────────────────────────────────────────────

function rsiMeta(rsi: number | null) {
  if (rsi == null) return null;
  if (rsi < 35)  return { label: `RSI ${rsi.toFixed(0)} oversold`,  color: "text-green-600 bg-green-50 border-green-200" };
  if (rsi < 50)  return { label: `RSI ${rsi.toFixed(0)} zona energi`, color: "text-teal-600 bg-teal-50 border-teal-200" };
  if (rsi > 65)  return { label: `RSI ${rsi.toFixed(0)} overbought`, color: "text-red-500 bg-red-50 border-red-200" };
  return { label: `RSI ${rsi.toFixed(0)} netral`, color: "text-neutral-500 bg-neutral-50 border-neutral-200" };
}

// ── Score bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ score, bar }: { score: number; bar: string }) {
  return (
    <div className="w-full h-1 bg-neutral-100 rounded-full overflow-hidden mt-1.5">
      <div className={`h-full rounded-full ${bar} transition-all duration-500`}
        style={{ width: `${Math.min(score, 99)}%` }} />
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Featured card (top 5) — NO price levels, reveals on click
// ══════════════════════════════════════════════════════════════════════════════

export function OpportunityFeatured({
  r, rank, isNew = false, onClick,
}: {
  r: OpportunityResult;
  rank: number;
  isNew?: boolean;
  onClick?: () => void;
}) {
  const base = r.symbol.replace("USDT", "");
  const sl   = scoreLabel(r.opportunity_score);
  const type = TYPE_META[r.alert_type] ?? TYPE_META.accumulation;
  const rsi  = rsiMeta(r.rsi_1h);

  return (
    <div
      onClick={onClick}
      className={`
        rounded-2xl border-2 bg-white flex flex-col
        hover:shadow-xl hover:-translate-y-0.5 transition-all duration-200 group
        ${onClick ? "cursor-pointer" : ""}
        ${sl.ring} ring-2
        ${isNew ? "shadow-teal-200 shadow-md" : ""}
      `}
    >
      {isNew && (
        <div className="h-0.5 rounded-t-2xl bg-gradient-to-r from-teal-400 via-teal-300 to-teal-400" />
      )}

      <div className="p-4 flex flex-col flex-1 gap-3">

        {/* ── Header: rank + coin + score ───────────────── */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="w-6 h-6 rounded-full bg-neutral-900 text-white text-[10px] font-black flex items-center justify-center shrink-0">
                {rank}
              </span>
              <h3 className="text-2xl font-black text-neutral-900 leading-none">{base}</h3>
              <span className="text-neutral-400 font-normal text-sm self-end pb-0.5">/USDT</span>
              {isNew && (
                <span className="text-[9px] bg-teal-500 text-white px-1.5 py-0.5 rounded font-bold">NEW</span>
              )}
            </div>
            <div className="flex items-center gap-1.5 flex-wrap ml-8">
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${type.bg}`}>
                {type.label}
              </span>
              {r.squeeze_tfs.length > 1 && (
                <span className="text-[9px] bg-purple-600 text-white px-1.5 py-0.5 rounded font-bold">
                  {r.squeeze_tfs.length}TF SQUEEZE
                </span>
              )}
              {/* §11.5: tandai kandidat yang akan DIEKSEKUSI agent otomatis */}
              {r.auto_open && (
                <span className="text-[9px] bg-neutral-900 text-teal-300 px-1.5 py-0.5 rounded font-bold">
                  🤖 AUTO
                </span>
              )}
              {r.weight_applied != null && r.weight_applied !== 1.0 && (
                <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold border ${
                  r.weight_applied > 1
                    ? "bg-green-50 text-green-700 border-green-200"
                    : "bg-red-50 text-red-600 border-red-200"
                }`}>
                  {r.weight_applied > 1 ? "↑" : "↓"}{r.weight_applied.toFixed(1)}x learning
                </span>
              )}
            </div>
          </div>

          {/* Score bubble */}
          <div className="flex flex-col items-center shrink-0">
            <div className={`w-14 h-14 rounded-full ${sl.bg} flex flex-col items-center justify-center ring-2 ring-white shadow`}>
              <span className="text-white font-black text-xl leading-none">{r.opportunity_score.toFixed(0)}</span>
              <span className="text-white/60 text-[9px]">pt</span>
            </div>
            <span className={`text-[10px] font-bold mt-0.5 ${sl.txt}`}>{sl.emoji} {sl.text}</span>
            <ScoreBar score={r.opportunity_score} bar={sl.bar} />
          </div>
        </div>

        {/* ── Current price ─────────────────────────────── */}
        <div className="flex items-center gap-3 bg-neutral-50 rounded-xl px-3 py-2">
          <div>
            <p className="text-[9px] text-neutral-400 font-semibold uppercase tracking-wide">Harga</p>
            <p className="text-lg font-black text-neutral-900 font-mono tabular-nums leading-tight">
              ${fmtPrice(r.current_price)}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <span className={`text-sm font-bold tabular-nums ${r.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
              {r.change_24h >= 0 ? "▲" : "▼"} {Math.abs(r.change_24h).toFixed(1)}%
            </span>
            <span className="text-neutral-400 text-xs">24h</span>
          </div>
        </div>

        {/* ── Signals ───────────────────────────────────── */}
        <div className="space-y-1.5 flex-1">
          {r.signals.slice(0, 3).map((s, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className={`w-1.5 h-1.5 rounded-full mt-[5px] shrink-0 ${type.dot}`} />
              <p className="text-[11px] text-neutral-600 leading-relaxed">{s}</p>
            </div>
          ))}
        </div>

        {/* ── Risk-adjusted metrics (§11.3): potensi · risiko · asimetri ── */}
        {(r.rr_ratio != null || r.tp2_net_pct != null) && (
          <div className="grid grid-cols-3 gap-1.5 bg-neutral-50 rounded-xl px-2.5 py-2">
            <div className="text-center">
              <p className="text-[8px] text-neutral-400 font-semibold uppercase">R:R</p>
              <p className="text-xs font-black text-neutral-800 tabular-nums">
                {r.rr_ratio != null ? `1:${r.rr_ratio}` : "—"}
              </p>
            </div>
            <div className="text-center">
              <p className="text-[8px] text-neutral-400 font-semibold uppercase">Risk</p>
              <p className="text-xs font-black text-red-500 tabular-nums">
                {r.risk_pct != null ? `${r.risk_pct.toFixed(1)}%` : "—"}
              </p>
            </div>
            <div className="text-center">
              <p className="text-[8px] text-neutral-400 font-semibold uppercase">TP2 net</p>
              <p className="text-xs font-black text-green-600 tabular-nums">
                {r.tp2_net_pct != null ? `+${r.tp2_net_pct.toFixed(1)}%` : "—"}
              </p>
            </div>
          </div>
        )}

        {/* ── Quality indicators (no prices) ────────────── */}
        <div className="flex flex-wrap gap-1.5">
          {r.vol_ratio >= 1.5 && (
            <span className="text-[10px] bg-teal-50 text-teal-700 border border-teal-200 px-2 py-0.5 rounded-full font-semibold">
              Vol {r.vol_ratio.toFixed(1)}x
            </span>
          )}
          {rsi && (
            <span className={`text-[10px] border px-2 py-0.5 rounded-full font-semibold ${rsi.color}`}>
              {rsi.label}
            </span>
          )}
          {r.bb_width_15m !== null && r.bb_width_15m < 3.5 && (
            <span className="text-[10px] bg-purple-50 text-purple-700 border border-purple-200 px-2 py-0.5 rounded-full font-semibold">
              BB {r.bb_width_15m.toFixed(1)}% squeeze
            </span>
          )}
        </div>

        {/* ── Footer: TFs + CTA ─────────────────────────── */}
        <div className="flex items-center justify-between pt-2 border-t border-neutral-100">
          <div className="flex gap-1">
            {r.tfs_confirmed.map(tf => (
              <span key={tf} className="bg-neutral-100 text-neutral-500 text-[9px] px-1.5 py-0.5 rounded font-mono">
                {tf}
              </span>
            ))}
          </div>
          <span className="text-[10px] text-teal-600 font-bold group-hover:text-teal-500 flex items-center gap-1">
            Analisis &amp; Entry →
          </span>
        </div>

      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Compact row (rank 6–30) — NO price levels
// ══════════════════════════════════════════════════════════════════════════════

export function OpportunityRow({
  r, rank, isNew = false, onClick,
}: {
  r: OpportunityResult;
  rank: number;
  isNew?: boolean;
  onClick?: () => void;
}) {
  const base = r.symbol.replace("USDT", "");
  const sl   = scoreLabel(r.opportunity_score);
  const type = TYPE_META[r.alert_type] ?? TYPE_META.accumulation;
  const rsi  = rsiMeta(r.rsi_1h);

  return (
    <div
      onClick={onClick}
      className={`
        flex items-center gap-3 px-4 py-3 border-b border-neutral-100
        hover:bg-neutral-50 transition-colors last:border-0 group
        ${onClick ? "cursor-pointer" : ""}
        ${isNew ? "bg-teal-50/40" : ""}
      `}
    >
      {/* Rank */}
      <span className="text-xs text-neutral-400 font-mono w-6 shrink-0 text-right">{rank}</span>

      {/* Score */}
      <div className={`w-10 h-10 rounded-full ${sl.bg} flex flex-col items-center justify-center shrink-0 shadow-sm`}>
        <span className="text-white font-black text-sm leading-none">{r.opportunity_score.toFixed(0)}</span>
        <span className="text-white/60 text-[8px]">pt</span>
      </div>

      {/* Coin + type + primary signal */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
          <span className="font-bold text-sm text-neutral-900">
            {base}<span className="text-neutral-400 font-normal text-xs">/USDT</span>
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-semibold ${type.bg}`}>
            {type.label}
          </span>
          {r.squeeze_tfs.length > 1 && (
            <span className="text-[9px] bg-purple-600 text-white px-1.5 py-0.5 rounded font-bold">
              {r.squeeze_tfs.join("+")} SQZ
            </span>
          )}
          {r.auto_open && (
            <span className="text-[9px] bg-neutral-900 text-teal-300 px-1.5 py-0.5 rounded font-bold">
              🤖 AUTO
            </span>
          )}
          {r.rr_ratio != null && (
            <span className="text-[9px] bg-neutral-100 text-neutral-600 px-1.5 py-0.5 rounded font-mono font-bold">
              R:R 1:{r.rr_ratio}
            </span>
          )}
          {isNew && (
            <span className="text-[9px] bg-teal-500 text-white px-1.5 py-0.5 rounded font-bold">NEW</span>
          )}
        </div>
        <p className="text-[10px] text-neutral-500 truncate">{r.signals[0] ?? ""}</p>
      </div>

      {/* 24h change */}
      <div className="text-right shrink-0 hidden sm:block w-16">
        <p className={`text-xs font-bold tabular-nums ${r.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
          {r.change_24h >= 0 ? "+" : ""}{r.change_24h.toFixed(1)}%
        </p>
        <p className="text-[9px] text-neutral-400">24h</p>
      </div>

      {/* RSI indicator */}
      <div className="shrink-0 hidden md:block">
        {rsi ? (
          <span className={`text-[10px] border px-2 py-0.5 rounded-full font-semibold ${rsi.color}`}>
            {rsi.label}
          </span>
        ) : (
          <span className="text-[9px] text-neutral-300">—</span>
        )}
      </div>

      {/* Vol */}
      <div className="shrink-0 hidden lg:block w-14 text-right">
        <p className={`text-xs font-semibold ${r.vol_ratio >= 2 ? "text-teal-600" : "text-neutral-400"}`}>
          {r.vol_ratio.toFixed(1)}x
        </p>
        <p className="text-[9px] text-neutral-400">vol</p>
      </div>

      {/* TF badges */}
      <div className="hidden xl:flex gap-1 shrink-0">
        {r.tfs_confirmed.map(tf => (
          <span key={tf} className="bg-neutral-100 text-neutral-500 text-[9px] px-1.5 py-0.5 rounded font-mono">
            {tf}
          </span>
        ))}
      </div>

      {/* CTA arrow */}
      <span className="text-[10px] text-neutral-300 group-hover:text-teal-500 font-bold transition-colors shrink-0">
        →
      </span>
    </div>
  );
}
