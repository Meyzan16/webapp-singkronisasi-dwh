"use client";
import { useCallback, useEffect, useState, useMemo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { OpportunityCard, OpportunityResult } from "./components/OpportunityCard";

const POLL_INTERVAL = 5 * 60 * 1000; // 5 menit

const ALERT_FILTERS = [
  { key: "ALL",          label: "Semua" },
  { key: "squeeze",      label: "⚡ Squeeze" },
  { key: "accumulation", label: "📦 Akumulasi" },
  { key: "breakout",     label: "🎯 Breakout" },
];

export default function OpportunityPage() {
  const [results, setResults]     = useState<OpportunityResult[]>([]);
  const [loading, setLoading]     = useState(true);
  const [lastUpdated, setLast]    = useState<Date | null>(null);
  const [scanned, setScanned]     = useState(0);
  const [alertFilter, setAlert]   = useState("ALL");
  const [search, setSearch]       = useState("");
  const [minScore, setMinScore]   = useState(30);
  const [generatedAt, setGen]     = useState(0);

  const fetchData = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const r = await fetch(`/api/v1/opportunity/scan?min_score=30&limit=50`);
      if (!r.ok) return;
      const d = await r.json();
      setResults(d.results ?? []);
      setScanned(d.scanned ?? 0);
      setGen(d.generated_at ?? 0);
      setLast(new Date());
    } catch { /* silent */ }
    finally { if (!silent) setLoading(false); }
  }, []);

  useEffect(() => { void fetchData(); }, [fetchData]);

  // Auto-refresh every 5 min
  useEffect(() => {
    const t = setInterval(() => void fetchData(true), POLL_INTERVAL);
    return () => clearInterval(t);
  }, [fetchData]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return results.filter(r => {
      if (alertFilter !== "ALL" && r.alert_type !== alertFilter) return false;
      if (r.opportunity_score < minScore) return false;
      if (q && !r.symbol.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [results, alertFilter, minScore, search]);

  // Counts per alert type
  const counts = useMemo(() => {
    const c: Record<string, number> = { ALL: results.length };
    results.forEach(r => { c[r.alert_type] = (c[r.alert_type] ?? 0) + 1; });
    return c;
  }, [results]);

  const topCount   = results.filter(r => r.opportunity_score >= 70).length;
  const watchCount = results.filter(r => r.opportunity_score >= 50 && r.opportunity_score < 70).length;

  const timeAgo = generatedAt
    ? Math.floor((Date.now() / 1000 - generatedAt) / 60)
    : null;

  return (
    <div className="space-y-4">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-5 pb-4">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-3 mb-1.5">
                <span className="text-3xl">🚀</span>
                <div>
                  <h1 className="text-2xl font-bold">Opportunity Scanner</h1>
                  <p className="text-xs text-neutral-400">Koin berpotensi naik · Multi-timeframe · Tidak peduli style</p>
                </div>
              </div>
              <p className="text-xs text-neutral-500 max-w-xl leading-relaxed mt-1">
                Mencari koin seperti <strong className="text-teal-300">OPN, DOGE, PEPE</strong> sebelum pump —
                BB Squeeze di 2+ timeframe, akumulasi smart money, RSI reset dari oversold.
                Tidak terikat style tertentu.
              </p>
            </div>
            <div className="text-right space-y-1.5">
              {/* Summary badges */}
              <div className="flex gap-2 justify-end">
                <div className="bg-green-500/20 border border-green-500/30 rounded-lg px-3 py-1.5 text-center">
                  <p className="text-green-400 font-black text-lg leading-tight">{topCount}</p>
                  <p className="text-[9px] text-green-500">🔥 High (≥70)</p>
                </div>
                <div className="bg-yellow-500/20 border border-yellow-500/30 rounded-lg px-3 py-1.5 text-center">
                  <p className="text-yellow-400 font-black text-lg leading-tight">{watchCount}</p>
                  <p className="text-[9px] text-yellow-500">⚡ Watch</p>
                </div>
                <div className="bg-neutral-700/50 border border-neutral-600 rounded-lg px-3 py-1.5 text-center">
                  <p className="text-neutral-300 font-black text-lg leading-tight">{scanned}</p>
                  <p className="text-[9px] text-neutral-500">pair scan</p>
                </div>
              </div>
              {lastUpdated && (
                <p className="text-[10px] text-neutral-500">
                  {timeAgo === 0 ? "baru saja" : `${timeAgo}m lalu`} · refresh tiap 5 menit
                </p>
              )}
              <button onClick={() => void fetchData()} disabled={loading}
                className="text-xs bg-teal-600 hover:bg-teal-500 disabled:opacity-50 px-3 py-1.5 rounded-lg transition-colors font-semibold">
                {loading ? "Scanning..." : "🔄 Scan Sekarang"}
              </button>
            </div>
          </div>

          {/* How it works */}
          <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            {[
              { icon: "⚡", text: "BB Squeeze 2+ TF → explosive move" },
              { icon: "📦", text: "Volume naik, harga flat → smart money" },
              { icon: "🔄", text: "RSI reset dari oversold → energy recharge" },
              { icon: "🎯", text: "Near breakout level → satu push lagi" },
            ].map(c => (
              <div key={c.icon} className="bg-white/5 rounded-lg px-3 py-2 flex items-center gap-2">
                <span>{c.icon}</span>
                <span className="text-neutral-400">{c.text}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── Filters ────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Alert type */}
        <div className="flex gap-1.5 flex-wrap">
          {ALERT_FILTERS.map(f => (
            <button key={f.key} onClick={() => setAlert(f.key)}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${
                alertFilter === f.key
                  ? "bg-teal-600 text-white"
                  : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200"
              }`}>
              {f.label} {counts[f.key] !== undefined ? `(${counts[f.key] ?? 0})` : ""}
            </button>
          ))}
        </div>

        {/* Min score */}
        <select value={minScore} onChange={e => setMinScore(Number(e.target.value))}
          className="px-2.5 py-1.5 bg-white border border-neutral-200 rounded-lg text-xs text-neutral-700 cursor-pointer">
          <option value={30}>Score ≥ 30</option>
          <option value={50}>Score ≥ 50</option>
          <option value={70}>Score ≥ 70 (🔥)</option>
        </select>

        {/* Search */}
        <div className="relative flex-1 min-w-[140px] max-w-xs">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-400 text-xs">🔍</span>
          <input type="text" placeholder="Cari symbol…" value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-7 pr-3 py-1.5 bg-white border border-neutral-200 rounded-lg text-xs focus:outline-none focus:border-teal-500" />
        </div>

        {filtered.length < results.length && (
          <span className="text-xs text-neutral-500">{filtered.length} dari {results.length} hasil</span>
        )}
      </div>

      {/* ── Score Legend ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-4 text-[10px] text-neutral-500 flex-wrap">
        <span className="font-semibold">Score:</span>
        {[
          { dot: "bg-green-500", label: "≥ 70 — High potential 🔥" },
          { dot: "bg-yellow-500", label: "50–69 — Watch closely ⚡" },
          { dot: "bg-neutral-400", label: "30–49 — Early signal 👀" },
        ].map(l => (
          <span key={l.label} className="flex items-center gap-1">
            <span className={`w-2 h-2 rounded-full ${l.dot}`} />
            {l.label}
          </span>
        ))}
      </div>

      {/* ── Loading ────────────────────────────────────────────────────────── */}
      {loading && !results.length && (
        <div className="py-16 text-center text-neutral-500">
          <div className="animate-pulse space-y-2">
            <p className="text-2xl">🚀</p>
            <p className="font-semibold">Scanning 100 pair multi-timeframe...</p>
            <p className="text-xs">Menganalisis BB Squeeze + Volume + RSI di 15m, 1H, 4H</p>
          </div>
        </div>
      )}

      {/* ── Empty ─────────────────────────────────────────────────────────── */}
      {!loading && filtered.length === 0 && results.length > 0 && (
        <div className="text-center text-neutral-500 py-10">
          <p className="text-xl mb-2">🔍</p>
          <p>Tidak ada hasil untuk filter ini</p>
          <button onClick={() => { setAlert("ALL"); setMinScore(30); setSearch(""); }}
            className="mt-2 text-xs text-teal-600 underline">Reset filter</button>
        </div>
      )}

      {/* ── Results Grid ──────────────────────────────────────────────────── */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filtered.map(r => (
            <OpportunityCard key={r.symbol} r={r} />
          ))}
        </div>
      )}

    </div>
  );
}
