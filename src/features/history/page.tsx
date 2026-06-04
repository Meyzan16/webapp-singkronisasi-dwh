"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AccuracyStats } from "./components/AccuracyStats";
import { EquityCurve }  from "./components/EquityCurve";
import { TradeTable }   from "./components/TradeTable";
import type { PaperTrade, HistoryStats, EquityPoint } from "@/types/history";

const POLL_INTERVAL = 30_000; // 30 detik

interface SchedulerInfo {
  running: boolean;
  cycle_count: number;
  interval_minutes: number;
  next_scan_in_min: number | null;
  total_logged: number;
  last_error: string | null;
}

export default function HistoryPage() {
  const [trades, setTrades]   = useState<PaperTrade[]>([]);
  const [stats, setStats]     = useState<HistoryStats | null>(null);
  const [equity, setEquity]   = useState<EquityPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [days, setDays]       = useState(14);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [scheduler, setScheduler] = useState<SchedulerInfo | null>(null);
  const [countdown, setCountdown] = useState(POLL_INTERVAL / 1000);
  const [isLive, setIsLive]   = useState(true);
  const daysRef = useRef(days);
  daysRef.current = days;

  const fetchAll = useCallback(async (d: number, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [tradesRes, statsRes, equityRes, healthRes] = await Promise.all([
        fetch(`/api/v1/history/trades?days=${d}`).then(r => r.ok ? r.json() : null),
        fetch("/api/v1/history/stats").then(r => r.ok ? r.json() : null),
        fetch("/api/v1/history/equity").then(r => r.ok ? r.json() : null),
        fetch("/health").then(r => r.ok ? r.json() : null),
      ]);
      if (Array.isArray(tradesRes?.trades)) setTrades(tradesRes.trades);
      if (statsRes?.overall && statsRes?.by_style) setStats(statsRes);
      if (Array.isArray(equityRes?.points)) setEquity(equityRes.points);
      if (healthRes?.scheduler) setScheduler(healthRes.scheduler);
      setLastUpdated(new Date());
    } catch { /* silent */ }
    finally { if (!silent) setLoading(false); }
  }, []);

  const forceCheck = async () => {
    setChecking(true);
    try {
      await fetch("/api/v1/history/check", { method: "POST" });
      await fetchAll(days);
      setCountdown(POLL_INTERVAL / 1000);
    } finally {
      setChecking(false);
    }
  };

  // Initial load
  useEffect(() => { void fetchAll(days); }, [fetchAll, days]);

  // Auto-poll every 30 detik
  useEffect(() => {
    if (!isLive) return;
    setCountdown(POLL_INTERVAL / 1000);

    const pollTimer = setInterval(() => {
      void fetchAll(daysRef.current, true);
      setCountdown(POLL_INTERVAL / 1000);
    }, POLL_INTERVAL);

    const tickTimer = setInterval(() => {
      setCountdown(prev => (prev > 1 ? prev - 1 : POLL_INTERVAL / 1000));
    }, 1000);

    return () => {
      clearInterval(pollTimer);
      clearInterval(tickTimer);
    };
  }, [fetchAll, isLive]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6 pb-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <span className="text-3xl">📊</span>
                <h1 className="text-3xl font-bold">Paper Trading History</h1>
              </div>
              <p className="text-sm opacity-70 max-w-2xl leading-relaxed">
                Setiap rekomendasi scanner <strong className="text-teal-300">otomatis dicatat</strong> sebagai simulasi trade.
                Pantau <strong className="text-yellow-300">akurasi per style</strong> dan <strong className="text-green-300">pertumbuhan equity</strong> selama uji coba 2 minggu sebelum live trading.
              </p>
            </div>
            <div className="flex flex-col items-end gap-2">
              {/* Live badge + scheduler status */}
              <div className="flex items-center gap-2 flex-wrap justify-end">
                {/* LIVE / PAUSED toggle */}
                <button
                  onClick={() => setIsLive(v => !v)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold transition-colors ${
                    isLive
                      ? "bg-red-500/20 text-red-400 border border-red-500/30"
                      : "bg-neutral-700 text-neutral-400 border border-neutral-600"
                  }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${isLive ? "bg-red-400 animate-pulse" : "bg-neutral-500"}`} />
                  {isLive ? "LIVE" : "PAUSED"}
                </button>

                {scheduler && (
                  <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-[10px] font-semibold ${
                    scheduler.running ? "bg-teal-500/20 text-teal-300" : "bg-neutral-700 text-neutral-400"
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${scheduler.running ? "bg-teal-400 animate-pulse" : "bg-neutral-500"}`} />
                    {scheduler.running
                      ? `⏱ Auto-scan tiap ${scheduler.interval_minutes}m · Siklus #${scheduler.cycle_count} · ${scheduler.next_scan_in_min !== null ? `next ${scheduler.next_scan_in_min}m lagi` : "menunggu..."}`
                      : "Scanner offline"}
                  </div>
                )}
              </div>

              {/* Last updated + countdown */}
              {lastUpdated && (
                <p className="text-[10px] text-neutral-400 tabular-nums">
                  Update: {lastUpdated.toLocaleTimeString()}
                  {isLive && <span className="ml-2 text-teal-400">· refresh {countdown}d lagi</span>}
                </p>
              )}

              <div className="flex gap-2">
                <select
                  value={days}
                  onChange={e => setDays(Number(e.target.value))}
                  className="text-xs bg-white/10 hover:bg-white/20 px-3 py-2 rounded-lg text-white border border-white/20 cursor-pointer">
                  <option value={7}>7 hari</option>
                  <option value={14}>14 hari</option>
                  <option value={30}>30 hari</option>
                </select>
                <button
                  onClick={() => void forceCheck()}
                  disabled={checking}
                  className="flex items-center gap-1.5 text-xs bg-teal-500 hover:bg-teal-400 disabled:opacity-50 px-3 py-2 rounded-lg transition-colors font-semibold">
                  {checking
                    ? <><span className="animate-spin w-3 h-3 border-2 border-white border-t-transparent rounded-full" /> Checking...</>
                    : "🔄 Cek Harga Sekarang"}
                </button>
              </div>
            </div>
          </div>

          {/* Info strip */}
          <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <InfoChip icon="🔭" text="Dari Early Breakout Scanner — TA engine 7 sinyal" />
            <InfoChip icon="✅" text="Market = harga sudah di area S/R, bisa entry sekarang" />
            <InfoChip icon="⏳" text="Limit = tunggu pullback/rally ke zona S/R dulu" />
            <InfoChip icon="📐" text="SL/TP dimonitor real Binance · 1% risk per trade" />
          </div>
        </CardContent>
      </Card>

      {/* Accuracy Stats */}
      {stats && <AccuracyStats stats={stats} />}

      {/* Equity Curve */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">📈 Kurva Pertumbuhan Equity</CardTitle>
        </CardHeader>
        <CardContent>
          <EquityCurve points={equity} />
        </CardContent>
      </Card>

      {/* Trade Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base flex-wrap gap-2">
            <span>📋 Riwayat Trade</span>
            <span className="text-xs font-normal text-neutral-400">
              {trades.length} total · {trades.filter(t => t.status === "open").length} open
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <TradeTable trades={trades} loading={loading} />
        </CardContent>
      </Card>
    </div>
  );
}

function InfoChip({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="bg-white/5 rounded-lg px-3 py-2 flex items-center gap-2">
      <span>{icon}</span>
      <span className="text-neutral-300">{text}</span>
    </div>
  );
}
