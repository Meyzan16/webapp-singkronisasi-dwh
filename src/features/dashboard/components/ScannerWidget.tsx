"use client";
import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface ScanSignal {
  symbol: string;
  direction: string;
  probability: number;
  current_price: number;
  entry: number;
  entry_zone_low: number | null;
  entry_zone_high: number | null;
  entry_type: string;   // "at_zone" | "wait_pullback" | "wait_rally" | "market"
  entry_note: string;
  change_24h: number;
  volume_ratio: number;
  signals: string[];
  key_level: number | null;
  stop_loss: number;
  take_profit: number;
  risk_reward: string;
  alert_type: string;
  style_note: string;
}

interface ScannerData {
  results: ScanSignal[];
  scanned: number;
  style: string;
  style_label: string;
  timeframe: string;
  generated_at: number;
}

interface ScannerWidgetProps { fullPage?: boolean; }

const ALERT_COLORS: Record<string, string> = {
  squeeze:      "border-purple-500/40 bg-purple-950/20",
  accumulation: "border-teal-500/40 bg-teal-950/20",
  breakout:     "border-yellow-500/40 bg-yellow-950/20",
  reversal:     "border-blue-500/40 bg-blue-950/20",
};

const ALERT_BADGES: Record<string, string> = {
  squeeze:      "bg-purple-600",
  accumulation: "bg-teal-600",
  breakout:     "bg-yellow-600",
  reversal:     "bg-blue-600",
};

const ALERT_LABELS: Record<string, string> = {
  squeeze:      "⚡ Squeeze",
  accumulation: "📦 Accum",
  breakout:     "🎯 Breakout",
  reversal:     "↩ Reversal",
};

const STYLES = [
  { key: "scalping",   label: "Scalping",  icon: "⚡", desc: "15m · Menit–Jam",    hint: "RSI ekstrem, vol spike, momentum cepat"   },
  { key: "daytrading", label: "Day Trade", icon: "📅", desc: "1H · Harian",        hint: "Balance trend & momentum, intraday setup"  },
  { key: "swing",      label: "Swing",     icon: "🌊", desc: "4H · Hari–Minggu",   hint: "BB squeeze, akumulasi, breakout multi-hari" },
  { key: "position",   label: "Position",  icon: "🏔", desc: "1D · Minggu–Bulan",  hint: "Akumulasi panjang, trend makro, S/R weekly" },
];

const fmtPrice = (p: number) =>
  p < 0.001 ? p.toFixed(6) : p < 1 ? p.toFixed(4) : p.toLocaleString(undefined, { maximumFractionDigits: 4 });

const probColor = (p: number) =>
  p >= 70 ? "text-green-400" : p >= 50 ? "text-yellow-400" : "text-neutral-400";

const probBar = (p: number) =>
  p >= 70 ? "bg-green-500" : p >= 50 ? "bg-yellow-500" : "bg-neutral-500";

export function ScannerWidget({ fullPage = false }: ScannerWidgetProps) {
  const [data, setData]       = useState<ScannerData | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter]   = useState<"ALL" | "LONG" | "SHORT">("ALL");
  const [style, setStyle]     = useState("swing"); // default Swing

  const fetchData = useCallback(async (s: string) => {
    try {
      setLoading(true);
      const r = await fetch(`/api/v1/scanner/scan?style=${s}`);
      setData(await r.json());
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
    void fetchData(s);
  };

  const filtered = data?.results.filter(r => filter === "ALL" || r.direction === filter) ?? [];
  const timeAgo  = data ? Math.floor((Date.now() / 1000 - data.generated_at) / 60) : 0;
  const longCount  = data?.results.filter(r => r.direction === "LONG").length ?? 0;
  const shortCount = data?.results.filter(r => r.direction === "SHORT").length ?? 0;

  return (
    <Card className="border-0 bg-neutral-950 text-white">
      <CardHeader className="pb-3">
        <CardTitle className="space-y-3">
          {/* Title row */}
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-xl">🔭</span>
              <div>
                <p className="text-sm font-bold leading-tight">Early Breakout Scanner</p>
                <p className="text-[10px] text-neutral-500 font-normal">Detects coiling, accumulation & breakout zones</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {loading && <span className="animate-spin w-3 h-3 border-2 border-teal-400 border-t-transparent rounded-full" />}
              {data && !loading && (
                <span className="text-[10px] text-neutral-500">
                  {data.style_label} ({data.timeframe}) · {data.scanned} pairs · {timeAgo === 0 ? "baru" : `${timeAgo}m lalu`}
                </span>
              )}
              <button onClick={() => void fetchData(tf)}
                className="text-xs bg-neutral-800 hover:bg-neutral-700 px-2 py-1 rounded-lg transition-colors text-neutral-300">
                ↻
              </button>
            </div>
          </div>

          {/* Trading style selector */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
            {STYLES.map(s => (
              <button key={s.key} onClick={() => handleStyleChange(s.key)}
                title={s.hint}
                className={`flex flex-col items-start px-3 py-2 rounded-xl border text-left transition-all ${
                  style === s.key
                    ? "bg-teal-600 border-teal-500 text-white shadow-sm"
                    : "bg-neutral-800 border-neutral-700 text-neutral-400 hover:border-teal-600/50 hover:text-neutral-100"
                }`}>
                <div className="flex items-center gap-1.5">
                  <span className="text-base">{s.icon}</span>
                  <span className="font-bold text-xs">{s.label}</span>
                </div>
                <span className={`text-[10px] mt-0.5 leading-tight ${style === s.key ? "opacity-80" : "opacity-50"}`}>
                  {s.desc}
                </span>
              </button>
            ))}
          </div>

          {/* Direction filter + stats */}
          <div className="flex items-center gap-2">
            {(["ALL", "LONG", "SHORT"] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
                  filter === f
                    ? f === "LONG"  ? "bg-green-600 text-white"
                    : f === "SHORT" ? "bg-red-600 text-white"
                    : "bg-teal-600 text-white"
                    : "bg-neutral-800 text-neutral-400 hover:text-white"
                }`}>
                {f === "ALL"   ? `All (${data?.results.length ?? 0})`
                : f === "LONG" ? `▲ Long (${longCount})`
                :                `▼ Short (${shortCount})`}
              </button>
            ))}
          </div>
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

        {loading && !data && (
          <div className="py-10 text-center text-neutral-500 text-sm">
            <div className="animate-pulse space-y-1">
              <p>🔭 Scanning 100 most active pairs...</p>
              <p className="text-[10px]">Detecting coils, accumulation & breakout zones</p>
            </div>
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <p className="text-center text-neutral-500 text-sm py-8">
            No early-warning setups found for {STYLES.find(s => s.key === style)?.label} style
          </p>
        )}

        {filtered.length > 0 && (
          <div className={fullPage ? "grid grid-cols-1 md:grid-cols-2 gap-2" : "space-y-2"}>
            {filtered.map((r) => {
              const base    = r.symbol.replace("USDT", "");
              const isLong  = r.direction === "LONG";
              const cardBg  = ALERT_COLORS[r.alert_type] ?? "border-neutral-800 bg-neutral-900/30";
              const badgeBg = ALERT_BADGES[r.alert_type] ?? "bg-neutral-700";

              return (
                <div key={r.symbol}
                  className={`rounded-xl p-3 border transition-all hover:brightness-110 ${cardBg}`}>

                  {/* Header row */}
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-black flex-shrink-0 ${
                        isLong ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                      }`}>
                        {base.slice(0, 4)}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-bold text-sm text-white">{base}/USDT</span>
                          <Badge className={`text-[10px] px-1.5 py-0 font-bold ${
                            isLong ? "bg-green-600" : "bg-red-600"
                          }`}>
                            {isLong ? "▲ LONG" : "▼ SHORT"}
                          </Badge>
                          <Badge className={`text-[10px] px-1.5 py-0 ${badgeBg}`}>
                            {ALERT_LABELS[r.alert_type]}
                          </Badge>
                        </div>
                        <p className="text-xs font-mono text-neutral-400 mt-0.5">${fmtPrice(r.current_price)}</p>
                      </div>
                    </div>

                    {/* Probability */}
                    <div className="text-right flex-shrink-0">
                      <p className={`text-xl font-black leading-tight ${probColor(r.probability)}`}>
                        {r.probability.toFixed(0)}
                        <span className="text-xs font-normal text-neutral-500">%</span>
                      </p>
                      <p className="text-[10px] text-neutral-500">probability</p>
                    </div>
                  </div>

                  {/* Probability bar */}
                  <div className="w-full bg-neutral-800 rounded-full h-1 mb-2">
                    <div className={`h-full rounded-full transition-all ${probBar(r.probability)}`}
                      style={{ width: `${r.probability}%` }} />
                  </div>

                  {/* Signals */}
                  <div className="space-y-0.5 mb-2">
                    {r.signals.map((s, i) => (
                      <p key={i} className="text-[10px] text-neutral-300 leading-relaxed">{s}</p>
                    ))}
                  </div>

                  {/* Entry zone note */}
                  {r.entry_note && (
                    <div className={`rounded-lg px-2.5 py-1.5 mb-1.5 text-[10px] leading-relaxed ${
                      r.entry_type === "at_zone"
                        ? "bg-green-900/40 text-green-300"
                        : "bg-amber-900/30 text-amber-300"
                    }`}>
                      {r.entry_note}
                    </div>
                  )}

                  {/* Entry + SL + TP */}
                  <div className="grid grid-cols-3 gap-1.5 mb-2">
                    <div className={`rounded-lg px-2 py-1.5 ${
                      r.entry_type === "at_zone" ? "bg-green-900/40" : "bg-amber-900/30"
                    }`}>
                      <p className="text-[9px] text-neutral-400 font-bold uppercase mb-0.5">
                        {r.entry_type === "at_zone" ? "✅ Entry" : "⏳ Limit"}
                      </p>
                      <p className="text-xs font-bold text-white font-mono">${fmtPrice(r.entry)}</p>
                      {r.entry_zone_low && (
                        <p className="text-[9px] text-neutral-500">
                          {fmtPrice(r.entry_zone_low)}–{fmtPrice(r.entry_zone_high!)}
                        </p>
                      )}
                    </div>
                    <div className="bg-black/20 rounded-lg px-2 py-1.5">
                      <p className="text-[9px] text-red-400 font-bold uppercase mb-0.5">⛔ SL</p>
                      <p className="text-xs font-bold text-red-300 font-mono">${fmtPrice(r.stop_loss)}</p>
                      <p className="text-[9px] text-neutral-500 truncate">{r.sl_method.split("(")[0]}</p>
                    </div>
                    <div className="bg-black/20 rounded-lg px-2 py-1.5">
                      <p className="text-[9px] text-green-400 font-bold uppercase mb-0.5">🎯 TP</p>
                      <p className="text-xs font-bold text-green-300 font-mono">${fmtPrice(r.take_profit)}</p>
                      <p className="text-[9px] text-neutral-500 truncate">{r.tp_method.split("$")[0]}</p>
                    </div>
                  </div>

                  {/* Stats row */}
                  <div className="flex items-center justify-between text-[10px] text-neutral-400 pt-1.5 border-t border-neutral-700/50">
                    <div className="flex gap-2">
                      <span className={r.change_24h >= 0 ? "text-green-400" : "text-red-400"}>
                        {r.change_24h >= 0 ? "+" : ""}{r.change_24h}%
                      </span>
                      <span>Vol <strong className="text-neutral-300">{r.volume_ratio}x</strong></span>
                    </div>
                    <span className="text-teal-400 font-bold text-sm">{r.risk_reward}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
