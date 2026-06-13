"use client";
import { useEffect, useState, useCallback } from "react";
import { fmtPrice } from "@/lib/format";
import { OpportunityResult, scoreLabel, TYPE_META } from "./OpportunityCard";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AnalysisResult {
  symbol:          string;
  entry:           number;
  sl:              number;
  tp1:             number;
  tp2:             number;
  tp3:             number;
  risk_pct:        number;
  tp1_pct:         number;
  tp2_pct:         number;
  tp3_pct:         number;
  rr_ratio:        number;
  taker_ratio:     number;
  taker_ratio_4h:  number;
  rsi_1h:          number;
  bb_width_1h:     number;
  ema_bullish:     boolean;
  depth_ratio:     number | null;   // order book bid ratio — None if unavailable
  signals:         string[];
  confidence:      number;
  below_standard?: boolean;         // §16.1: TP asli < standar R:R engine
  elapsed_sec:     number;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function LevelRow({
  label, price, pct, isEntry = false, isMain = false, isDanger = false,
}: {
  label: string; price: number; pct: number;
  isEntry?: boolean; isMain?: boolean; isDanger?: boolean;
}) {
  return (
    <div className={`flex items-center gap-3 px-3 py-1.5 rounded-lg ${
      isEntry ? "bg-neutral-100 my-0.5" : isMain ? "bg-green-50 ring-1 ring-green-200" : ""
    }`}>
      <span className={`text-[10px] font-mono uppercase w-12 shrink-0 font-bold ${
        isEntry ? "text-neutral-700" : isMain ? "text-green-700" : isDanger ? "text-red-400" : "text-neutral-400"
      }`}>{label}</span>
      <span className={`flex-1 text-base font-black font-mono tabular-nums ${
        isEntry ? "text-neutral-900" : isMain ? "text-green-700" : isDanger ? "text-red-500" : "text-green-600"
      }`}>${fmtPrice(price)}</span>
      {pct !== 0 && (
        <span className={`text-sm font-bold tabular-nums ${isDanger ? "text-red-500" : "text-green-600"}`}>
          {pct > 0 ? "+" : ""}{pct.toFixed(2)}%
        </span>
      )}
      {isEntry && <span className="text-[9px] text-neutral-500 font-semibold bg-neutral-200 px-1.5 py-0.5 rounded">ENTRY</span>}
    </div>
  );
}

function RangeBar({ entry, sl, tp2, tp3 }: { entry: number; sl: number; tp2: number; tp3: number }) {
  const total = tp3 - sl;
  if (total <= 0) return null;
  const ep  = ((entry - sl) / total) * 100;
  const t2p = ((tp2   - sl) / total) * 100;
  return (
    <div className="relative h-3 bg-neutral-200 rounded-full my-3">
      <div className="absolute left-0 h-full bg-red-300 rounded-l-full" style={{ width: `${ep.toFixed(1)}%` }} />
      <div className="absolute h-full bg-green-400" style={{ left: `${ep.toFixed(1)}%`, width: `${(t2p - ep).toFixed(1)}%` }} />
      <div className="absolute h-full bg-green-200 rounded-r-full" style={{ left: `${t2p.toFixed(1)}%`, right: 0 }} />
      <div className="absolute w-1.5 h-5 bg-neutral-800 rounded-sm -top-1 shadow"
        style={{ left: `${ep.toFixed(1)}%`, transform: "translateX(-50%)" }} />
      <div className="absolute -bottom-5 flex justify-between w-full text-[9px] font-bold px-0.5">
        <span className="text-red-500">SL</span>
        <span className="text-neutral-600" style={{ position: "absolute", left: `${ep.toFixed(1)}%`, transform: "translateX(-50%)" }}>Entry</span>
        <span className="text-green-600" style={{ position: "absolute", left: `${t2p.toFixed(1)}%`, transform: "translateX(-50%)" }}>TP2</span>
        <span className="text-green-400">TP3</span>
      </div>
    </div>
  );
}

function StatBox({ label, value, sub, highlight }: { label: string; value: string; sub?: string; highlight?: string }) {
  return (
    <div className="bg-neutral-50 rounded-xl p-3 text-center">
      <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold mb-0.5">{label}</p>
      <p className={`text-lg font-black ${highlight ?? "text-neutral-800"}`}>{value}</p>
      {sub && <p className="text-[9px] text-neutral-400 mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Modal ──────────────────────────────────────────────────────────────────────

export function CoinModal({
  r,
  onClose,
}: {
  r: OpportunityResult;
  onClose: () => void;
}) {
  const base = r.symbol.replace("USDT", "");
  const sl   = scoreLabel(r.opportunity_score);
  const type = TYPE_META[r.alert_type] ?? TYPE_META.accumulation;

  // Analysis state — refreshed on open
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeErr, setAnalyzeErr] = useState("");

  // One-position rule: existing open position check
  const [existingPos, setExistingPos] = useState<{ symbol: string; entry: number } | null>(null);

  // Position creation state
  const [opening, setOpening]   = useState(false);
  const [opened, setOpened]     = useState(false);
  const [openErr, setOpenErr]   = useState("");

  // Determine current levels (analyzer > scanner).
  // §16.4: fallback dari data SCAN — nilai yang tidak diketahui dikirim NETRAL
  // (taker 0.5, confidence 50), bukan angka karangan yang mencemari training.
  const usingFallback = analysis === null;
  const levels = analysis ?? (r.entry != null ? {
    entry: r.entry!, sl: r.sl!, tp1: r.tp1!, tp2: r.tp2!, tp3: r.tp3!,
    risk_pct: r.risk_pct!, tp1_pct: r.tp1_pct!, tp2_pct: r.tp2_pct!, tp3_pct: r.tp3_pct!,
    rr_ratio: r.rr_ratio!, taker_ratio: 0.5, taker_ratio_4h: 0.5,
    rsi_1h: r.rsi_1h ?? 50, bb_width_1h: r.bb_width_15m ?? 0,
    ema_bullish: false, depth_ratio: null, signals: r.signals, confidence: 50, elapsed_sec: 0,
    symbol: r.symbol,
  } : null);
  const belowStandard = analysis?.below_standard === true;

  // Run analyzer when modal opens
  const runAnalyzer = useCallback(async () => {
    setAnalyzing(true);
    setAnalyzeErr("");
    try {
      const res = await fetch(`/api/v1/opportunity/analyze/${r.symbol}`);
      if (!res.ok) throw new Error("Gagal menganalisis");
      const data = await res.json() as AnalysisResult;
      setAnalysis(data);
    } catch {
      setAnalyzeErr("Analisis gagal — menggunakan data scan terakhir");
    } finally {
      setAnalyzing(false);
    }
  }, [r.symbol]);

  // Per-coin rule: lock only if THIS exact coin already has an open position
  const checkExistingPosition = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/opportunity/positions");
      if (!res.ok) return;
      const d = await res.json() as { positions: Array<{ symbol: string; entry: number; status: string }> };
      const sameOpen = d.positions.find(p => p.status === "open" && p.symbol === r.symbol);
      setExistingPos(sameOpen ? { symbol: sameOpen.symbol, entry: sameOpen.entry } : null);
    } catch { /* silent */ }
  }, [r.symbol]);

  useEffect(() => {
    void runAnalyzer();
    void checkExistingPosition();
  }, [runAnalyzer, checkExistingPosition]);

  // Keyboard close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, []);

  // Open position
  const handleOpenTrade = async () => {
    if (!levels) return;
    setOpening(true);
    setOpenErr("");
    try {
      const body = {
        symbol:            r.symbol,
        entry:             levels.entry,
        sl:                levels.sl,
        tp1:               levels.tp1,
        tp2:               levels.tp2,
        tp3:               levels.tp3,
        risk_pct:          levels.risk_pct,
        tp1_pct:           levels.tp1_pct,
        tp2_pct:           levels.tp2_pct,
        tp3_pct:           levels.tp3_pct,
        rr_ratio:          levels.rr_ratio,
        opportunity_score: r.opportunity_score,
        alert_type:        r.alert_type,
        signals:           levels.signals.slice(0, 4),
        taker_ratio:       levels.taker_ratio,
        confidence:        levels.confidence,
      };
      const res = await fetch("/api/v1/opportunity/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json() as { detail?: string };
        throw new Error(err.detail ?? "Gagal membuka posisi");
      }
      setOpened(true);
      // Refresh existing position state after successful open
      await checkExistingPosition();
    } catch (e) {
      setOpenErr((e as Error).message);
    } finally {
      setOpening(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-white w-full sm:max-w-lg rounded-t-3xl sm:rounded-2xl shadow-2xl overflow-hidden max-h-[92vh] flex flex-col">

        {/* Mobile handle */}
        <div className="flex justify-center pt-3 pb-1 sm:hidden">
          <div className="w-10 h-1 bg-neutral-300 rounded-full" />
        </div>

        {/* Header */}
        <div className="p-5 pb-4 bg-gradient-to-br from-neutral-900 to-neutral-800 text-white">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <h2 className="text-3xl font-black">{base}</h2>
                <span className="text-neutral-400 text-lg font-normal self-end pb-0.5">/USDT</span>
                {analyzing && (
                  <span className="flex items-center gap-1 text-[10px] text-teal-300 bg-teal-500/20 px-2 py-0.5 rounded-full">
                    <span className="w-2 h-2 border border-teal-300 border-t-transparent rounded-full animate-spin" />
                    Menganalisis...
                  </span>
                )}
                {analysis && !analyzing && (
                  <span className="text-[9px] text-green-400 bg-green-500/20 px-2 py-0.5 rounded-full font-bold">
                    ✓ Fresh {analysis.elapsed_sec}s
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full border ${type.bg}`}>{type.label}</span>
                {r.squeeze_tfs.length > 1 && (
                  <span className="text-[11px] bg-purple-600 text-white px-2 py-0.5 rounded font-bold">
                    {r.squeeze_tfs.length}TF SQUEEZE
                  </span>
                )}
                <span className={`text-[11px] font-bold px-2 py-0.5 rounded-lg border ${sl.badge}`}>
                  {sl.emoji} {sl.text}
                </span>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="flex flex-col items-center">
                <div className={`w-16 h-16 rounded-full ${sl.bg} flex flex-col items-center justify-center ring-2 ring-white/30 shadow-lg`}>
                  <span className="text-white font-black text-2xl leading-none">{r.opportunity_score.toFixed(0)}</span>
                  <span className="text-white/60 text-[9px]">pt</span>
                </div>
                {analysis && (
                  <span className="text-[9px] text-yellow-400 mt-1 font-bold">{analysis.confidence}% conf</span>
                )}
              </div>
              <button onClick={onClose}
                className="w-8 h-8 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center text-white transition-colors">✕</button>
            </div>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto flex-1 p-5 space-y-5">

          {/* Current price */}
          <div className="flex items-center justify-between bg-neutral-50 rounded-2xl px-4 py-3">
            <div>
              <p className="text-[10px] text-neutral-400 font-semibold uppercase tracking-wide">Harga Sekarang</p>
              <p className="text-3xl font-black text-neutral-900 font-mono tabular-nums leading-tight">
                ${fmtPrice(r.current_price)}
              </p>
            </div>
            <div className="text-right space-y-1">
              <p className={`text-lg font-black tabular-nums ${r.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
                {r.change_24h >= 0 ? "▲" : "▼"} {Math.abs(r.change_24h).toFixed(2)}%
              </p>
              <p className="text-[10px] text-neutral-400">24 jam</p>
              {r.change_1h !== 0 && (
                <p className={`text-sm font-semibold ${r.change_1h >= 0 ? "text-green-500" : "text-red-400"}`}>
                  {r.change_1h >= 0 ? "▲" : "▼"} {Math.abs(r.change_1h).toFixed(2)}%
                  <span className="text-neutral-400 font-normal"> 1j</span>
                </p>
              )}
            </div>
          </div>

          {/* Position levels */}
          {levels ? (
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">Rekomendasi Posisi SPOT</p>
                {analyzeErr && <p className="text-[9px] text-amber-500">{analyzeErr}</p>}
              </div>
              {/* §16.1: resistance asli tidak memenuhi standar R:R engine */}
              {belowStandard && (
                <div className="mb-2 text-[10px] bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5 text-amber-700">
                  ⚠️ Resistance terdekat di bawah standar R:R — target diangkat ke
                  minimum engine. Pertimbangkan skip; struktur harga belum ideal.
                </div>
              )}
              {usingFallback && !analyzing && (
                <p className="mb-2 text-[9px] text-neutral-400">
                  Sumber level: hasil scan terakhir (analyzer tidak tersedia)
                </p>
              )}
              <div className="border border-neutral-100 rounded-2xl overflow-hidden">
                <div className="px-3 py-2">
                  <LevelRow label="TP3"   price={levels.tp3}  pct={levels.tp3_pct}  />
                  <LevelRow label="TP2 ★" price={levels.tp2}  pct={levels.tp2_pct}  isMain />
                  <LevelRow label="TP1"   price={levels.tp1}  pct={levels.tp1_pct}  />
                  <LevelRow label="Entry" price={levels.entry} pct={0}              isEntry />
                  <LevelRow label="SL"    price={levels.sl}   pct={-levels.risk_pct} isDanger />
                </div>
              </div>
              <div className="px-1 mt-2 mb-7">
                <RangeBar entry={levels.entry} sl={levels.sl} tp2={levels.tp2} tp3={levels.tp3} />
              </div>
              <div className="flex items-center gap-3 mt-6 flex-wrap">
                <div className="bg-green-100 border border-green-200 rounded-xl px-4 py-2 text-center">
                  <p className="text-[10px] text-green-600 font-semibold">R:R Ratio</p>
                  <p className="text-xl font-black text-green-700">1:{levels.rr_ratio}</p>
                </div>
                <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-2 text-center">
                  <p className="text-[10px] text-red-400 font-semibold">Risiko (SL)</p>
                  <p className="text-xl font-black text-red-500">-{levels.risk_pct}%</p>
                </div>
                <div className="bg-green-50 border border-green-100 rounded-xl px-4 py-2 text-center">
                  <p className="text-[10px] text-green-500 font-semibold">Target (TP2)</p>
                  <p className="text-xl font-black text-green-600">+{levels.tp2_pct}%</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-center py-6">
              <div className="w-8 h-8 border-2 border-teal-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
              <p className="text-sm text-neutral-500">Menghitung level posisi...</p>
            </div>
          )}

          {/* Signals */}
          <div>
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2">Sinyal Teknikal</p>
            <div className="space-y-2">
              {(analysis?.signals ?? r.signals).map((s, i) => (
                <div key={i} className="flex items-start gap-3 bg-neutral-50 rounded-xl px-3 py-2.5">
                  <span className={`w-2 h-2 rounded-full mt-1 shrink-0 ${type.dot}`} />
                  <p className="text-sm text-neutral-700 leading-relaxed">{s}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Stats */}
          <div>
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2">Statistik</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <StatBox label="Volume" value={`${r.vol_ratio.toFixed(1)}x`} sub="vs rata-rata" />
              <StatBox
                label="RSI (1h)"
                value={(analysis?.rsi_1h ?? r.rsi_1h ?? 50).toFixed(0)}
                sub={(() => {
                  const v = analysis?.rsi_1h ?? r.rsi_1h ?? 50;
                  return v < 35 ? "⚠️ Oversold" : v > 65 ? "🔴 Overbought" : "✅ Normal";
                })()}
                highlight={(() => {
                  const v = analysis?.rsi_1h ?? r.rsi_1h ?? 50;
                  return v < 35 ? "text-green-600" : v > 65 ? "text-red-500" : "text-neutral-800";
                })()}
              />
              {analysis ? (
                <StatBox
                  label="Taker Buy"
                  value={`${(analysis.taker_ratio * 100).toFixed(0)}%`}
                  sub={analysis.taker_ratio >= 0.55 ? "🟢 Bullish" : analysis.taker_ratio <= 0.45 ? "🔴 Bearish" : "⚪ Netral"}
                  highlight={analysis.taker_ratio >= 0.55 ? "text-green-600" : analysis.taker_ratio <= 0.45 ? "text-red-500" : "text-neutral-800"}
                />
              ) : (
                r.bb_width_15m !== null && (
                  <StatBox label="BB Width" value={`${r.bb_width_15m.toFixed(1)}%`} sub="15m squeeze" />
                )
              )}
              {analysis?.depth_ratio != null ? (
                <StatBox
                  label="Order Book"
                  value={`${(analysis.depth_ratio * 100).toFixed(0)}% bid`}
                  sub={analysis.depth_ratio > 0.58 ? "📊 Bid kuat" : analysis.depth_ratio < 0.42 ? "📊 Ask kuat" : "📊 Seimbang"}
                  highlight={analysis.depth_ratio > 0.55 ? "text-green-600" : analysis.depth_ratio < 0.45 ? "text-red-500" : "text-neutral-800"}
                />
              ) : analysis ? (
                <StatBox label="Order Book" value="—" sub="tidak tersedia" />
              ) : null}
            </div>
          </div>

          {/* Timeframes */}
          <div>
            <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-2">Timeframe Terkonfirmasi</p>
            <div className="flex gap-2 flex-wrap">
              {r.tfs_confirmed.map(tf => (
                <span key={tf} className="bg-neutral-900 text-white text-xs font-bold px-3 py-1.5 rounded-full font-mono">{tf}</span>
              ))}
              {r.squeeze_tfs.length > 0 && (
                <span className="bg-purple-600 text-white text-xs font-bold px-3 py-1.5 rounded-full">
                  BB Squeeze: {r.squeeze_tfs.join(" + ")}
                </span>
              )}
            </div>
          </div>

          {/* Action buttons */}
          {opened ? (
            <div className="bg-green-50 border border-green-200 rounded-2xl px-4 py-4 text-center">
              <p className="text-2xl mb-1">✅</p>
              <p className="font-bold text-green-700">Posisi berhasil dibuka!</p>
              <p className="text-xs text-green-600 mt-1">
                Lihat di <strong>History → Opportunity SPOT</strong>
              </p>
              <button onClick={onClose}
                className="mt-3 text-xs bg-green-600 hover:bg-green-500 text-white font-semibold px-4 py-2 rounded-xl transition-colors">
                Tutup
              </button>
            </div>

          ) : existingPos ? (
            /* ── One-position rule: existing open position ──────────────── */
            <div className="space-y-2">
              <div className="bg-amber-50 border border-amber-200 rounded-2xl px-4 py-4">
                <div className="flex items-start gap-3">
                  <span className="text-2xl shrink-0">🔒</span>
                  <div>
                    <p className="font-bold text-amber-800 text-sm">
                      {existingPos.symbol.replace("USDT", "")} sudah punya posisi terbuka
                    </p>
                    <p className="text-xs text-amber-700 mt-1">
                      Entry <strong>${existingPos.entry.toLocaleString()}</strong> —
                      tunggu TP atau SL tercapai dulu.
                    </p>
                    <p className="text-xs text-amber-600 mt-2 leading-relaxed">
                      Koin lain masih bisa dibuka. Satu posisi per koin — seperti trading nyata.
                    </p>
                  </div>
                </div>
              </div>
              <button
                onClick={onClose}
                className="w-full text-xs text-neutral-400 hover:text-neutral-600 py-2 transition-colors"
              >
                Tutup
              </button>
            </div>

          ) : (
            /* ── Normal: open new position ──────────────────────────────── */
            <div className="space-y-2">
              {openErr && (
                <p className="text-xs text-red-500 text-center bg-red-50 rounded-lg px-3 py-2">{openErr}</p>
              )}
              <button
                onClick={() => void handleOpenTrade()}
                disabled={opening || !levels}
                className="flex items-center justify-center gap-2 w-full bg-teal-600 hover:bg-teal-500 disabled:opacity-40 text-white font-bold py-4 rounded-2xl transition-colors text-sm"
              >
                {opening ? (
                  <>
                    <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Membuka posisi...
                  </>
                ) : (
                  <>📈 Buka Posisi SPOT</>
                )}
              </button>
              <button
                onClick={onClose}
                className="w-full text-xs text-neutral-400 hover:text-neutral-600 py-2 transition-colors"
              >
                Batal
              </button>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
