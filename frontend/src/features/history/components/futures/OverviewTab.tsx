"use client";
import { useState } from "react";
import { WinRateBar } from "@/components/ui/stat-card";
import { ChartCarousel, type CarouselSlide } from "@/components/ui/chart-carousel";
import { DBHistoryTable } from "@/features/health/components/DBHistoryTable";
import { GateBanner } from "./GateBanner";
import { OpenPosCard } from "./OpenPosCard";
import { PnlCalendar } from "../PnlCalendar";
import { FuturesWalletChips } from "./FuturesWalletChips";
import type { OppPosition } from "../OppSpotTypes";
import type { FuturesPosition, RiskDashboard, LearningStats, RiskPosition } from "./types";

const TARGET_WIN_RATE = 80;

function fmtMonth(m: string): string {
  const [y, mo] = m.split("-");
  const names = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"];
  return `${names[parseInt(mo)]} ${y}`;
}

const REGIME_CFG: Record<string, { emoji: string; label: string; cls: string }> = {
  trending_up:   { emoji: "📈", label: "Trending Up",   cls: "bg-green-100 text-green-700 border-green-300"    },
  trending_down: { emoji: "📉", label: "Trending Down", cls: "bg-red-100 text-red-600 border-red-300"          },
  ranging:       { emoji: "↔️", label: "Ranging",       cls: "bg-blue-100 text-blue-700 border-blue-300"       },
  volatile:      { emoji: "⚡", label: "Volatile",      cls: "bg-orange-100 text-orange-700 border-orange-300" },
};

interface Props {
  riskDash:        RiskDashboard | null;
  learning:        LearningStats | null;
  startingBalance: number;
  riskDollar:      number;
  equityPoints:    { balance: number; n: number; symbol: string; win: boolean }[];
  stats: {
    open: number; closed: number; wins: number; losses: number; winRate: number;
    currentBalance: number; totalPnl$: number;
    agOpen: FuturesPosition[];
    ag: { total: number; wins: number; rate: number; pnl$: number };
  };
  autoThreshold:   number | null;
  autoPerAgent:    Record<string, number>;   // PLAN_v12 P2-B4
  agentFilter:     "all" | AgentKey;
  setAgentFilter:  (f: "all" | AgentKey) => void;
  countdown:       number;
  lastUpdated:     Date | null;
  loading:         boolean;
  calendarMap:     Map<string, number>;   // PLAN_v11 P5 E1
  closedTrades:    FuturesPosition[];      // PLAN_v11 P5 E1 — detail per-hari
  onRefresh:       () => void;
  onWalletChanged: () => void;
}

type AgentKey = "agentic";

export function OverviewTab({ riskDash, learning, startingBalance, riskDollar,
  equityPoints, stats,
  countdown, lastUpdated, loading, calendarMap, closedTrades, onRefresh, onWalletChanged }: Props) {

  const [selectedMonth, setSelectedMonth] = useState("all");

  const balanceColor = stats.currentBalance >= startingBalance ? "text-green-600" : "text-red-500";
  const pnlColor     = stats.totalPnl$ >= 0 ? "text-green-600" : "text-red-500";

  const riskMap: Record<number, RiskPosition> = {};
  (riskDash?.positions ?? []).forEach(rp => { riskMap[rp.id] = rp; });

  const AGENTS = [
    // Fase 8: satu agen. Empat lane lama dihapus bersama modulnya setelah
    // trade era mereka tutup semuanya.
    { key: "agentic" as AgentKey,        label: "Agentic",      color: "teal",   emoji: "🧠", data: stats.ag, positions: stats.agOpen, bg: "bg-teal-50 border-teal-100",     txt: "text-teal-700" },
  ];

  const hasOpen = AGENTS.some(a => a.positions.length > 0);

  return (
    <div className="space-y-5">
      <GateBanner gate={riskDash?.gate} />

      {/* Balance banner */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white overflow-hidden p-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <p className="text-xs text-neutral-400 mb-1 font-semibold uppercase tracking-wider">Simulasi Paper Trading</p>
            <div className="flex items-baseline gap-2">
              <span className={`text-4xl font-black tabular-nums ${balanceColor}`}>${stats.currentBalance.toFixed(2)}</span>
              <span className={`text-sm font-bold ${pnlColor}`}>{stats.totalPnl$ >= 0 ? "+" : ""}${stats.totalPnl$.toFixed(2)}</span>
            </div>
            <p className="text-xs text-neutral-400 mt-1">
              Modal awal <strong className="text-neutral-200">${startingBalance.toLocaleString()}</strong>
              {" · "}Risk <strong className="text-yellow-300">${riskDollar.toFixed(0)}/trade (1%)</strong>
              {" · "}Target R:R ≥ 1:3
            </p>
            {/* PLAN_v12 P6-F0 — Bebas/Terkunci + Deposit/Withdraw (ganti panel Dompet penuh) */}
            <div className="mt-2">
              <FuturesWalletChips onChanged={onWalletChanged} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-center">
            {[
              { label: "Open",   value: stats.open,    color: "text-blue-400"    },
              { label: "Closed", value: stats.closed,  color: "text-neutral-200" },
              { label: "Win",    value: stats.wins,    color: "text-green-400"   },
              { label: "Loss",   value: stats.losses,  color: "text-red-400"     },
            ].map(s => (
              <div key={s.label} className="bg-white/5 rounded-xl px-3 py-2">
                <p className={`text-2xl font-black ${s.color}`}>{s.value}</p>
                <p className="text-[9px] text-neutral-400">{s.label}</p>
              </div>
            ))}
          </div>
        </div>

        {stats.closed > 0 && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs text-neutral-400 font-semibold">Win Rate</span>
              <span className={`text-sm font-black ${stats.winRate >= 50 ? "text-green-400" : "text-red-400"}`}>{stats.winRate.toFixed(0)}%</span>
            </div>
            <div className="h-2 bg-neutral-700 rounded-full overflow-hidden">
              <div className={`h-full rounded-full transition-all duration-700 ${stats.winRate >= 60 ? "bg-green-500" : stats.winRate >= 50 ? "bg-yellow-500" : "bg-red-500"}`}
                style={{ width: `${Math.min(stats.winRate, 100)}%` }} />
            </div>
            <div className="flex justify-between text-[9px] text-neutral-500 mt-0.5">
              <span>Target 80%</span>
              <span className="text-neutral-300">{stats.wins}W / {stats.losses}L dari {stats.closed} trades</span>
            </div>
          </div>
        )}
      </div>

      {/* PLAN_v12 P6-F0: panel "Dompet Futures" dibuang (duplikat balance banner).
          P6-F4: Big Movers Watchlist dipindah ke halaman Futures Market. */}

      {/* Open positions */}
      {hasOpen && (
        <div>
          {/* Satu agen, jadi tak ada lagi yang perlu "dipisah per strategi".
              Pembungkus per-kategori tinggal satu kotak yang membungkus dirinya
              sendiri — dan kartunya melebar penuh karena grid-nya per-lane. */}
          <h3 className="text-sm font-bold text-neutral-700 mb-3">
            🔵 Posisi Terbuka ({stats.open})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 items-start">
            {stats.agOpen.map(p => (
              <OpenPosCard key={p.id} p={p} risk={riskMap[p.id]} riskDollar={riskDollar} />
            ))}
          </div>
        </div>
      )}

      {/* Kartu "perbandingan antar-agen" dibuang: dengan satu agen tak ada yang
          dibandingkan, dan kartunya hanya mengulang angka yang sudah ada di
          banner saldo persis di atasnya. */}

      {/* Regime + monitor status — chip ringkas (di luar carousel) */}
      {learning && (
        <div className="flex flex-wrap gap-2 items-center">
          {(() => {
            const cfg = REGIME_CFG[learning.regime] ?? { emoji: "🔍", label: learning.regime, cls: "bg-neutral-100 text-neutral-600 border-neutral-300" };
            return (
              <span className={`flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border ${cfg.cls}`}>
                {cfg.emoji} Regime: {cfg.label}
              </span>
            );
          })()}
          {learning.monitor?.running && (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-teal-700 bg-teal-50 border border-teal-200 px-3 py-1.5 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
              Monitor aktif · Liq Guards: {learning.monitor.liq_guards ?? 0} · TP Extended: {learning.monitor.tp_extended ?? 0}
            </span>
          )}
          {learning.overall.closed > 0 && (
            <span className={`text-xs font-bold px-3 py-1.5 rounded-full border ${
              learning.overall.win_rate >= TARGET_WIN_RATE ? "bg-green-100 text-green-700 border-green-300" : "bg-yellow-100 text-yellow-700 border-yellow-300"
            }`}>
              {learning.overall.win_rate.toFixed(0)}% / {TARGET_WIN_RATE}% target{learning.overall.win_rate >= TARGET_WIN_RATE ? " 🎯" : ""}
            </span>
          )}
        </div>
      )}

      {/* PLAN_v12 P6 F1-F3 — chart analitik dalam CAROUSEL (ringkas, 1 terlihat) */}
      {(() => {
        const slides: CarouselSlide[] = [];
        if (closedTrades.length > 0) {
          slides.push({ key: "cal", label: "📆 Kalender", node: (
            <PnlCalendar calendarMap={calendarMap} closedTrades={closedTrades as unknown as OppPosition[]} balance={stats.currentBalance} />
          )});
        }
        if (equityPoints.length > 1) {
          slides.push({ key: "eq", label: "📈 Balance", node: (
            <div className="p-1">
              <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📈 Pertumbuhan Balance (per trade)</p>
              <div className="flex items-end gap-0.5 h-16">
                {equityPoints.map((pt, i) => {
                  const minBal = Math.min(...equityPoints.map(p => p.balance));
                  const maxBal = Math.max(...equityPoints.map(p => p.balance));
                  const heightPct = ((pt.balance - minBal) / Math.max(maxBal - minBal, 1)) * 100;
                  return (
                    <div key={i} title={pt.n === 0 ? `Start $${pt.balance.toFixed(0)}` : `#${pt.n} ${pt.symbol} → $${pt.balance.toFixed(0)}`}
                      className={`flex-1 min-w-[3px] rounded-t transition-all ${i === 0 ? "bg-neutral-300" : pt.win ? "bg-green-400" : "bg-red-400"}`}
                      style={{ height: `${Math.max(heightPct, 5)}%` }} />
                  );
                })}
              </div>
              <div className="flex justify-between text-[9px] text-neutral-400 mt-1">
                <span>${startingBalance.toLocaleString()} start</span>
                <span className={`font-bold ${balanceColor}`}>${stats.currentBalance.toFixed(0)} sekarang</span>
              </div>
            </div>
          )});
        }
        if (learning && learning.win_rate_trend.length > 2) {
          slides.push({ key: "trend", label: "📊 WR Trend", node: (
            <div className="p-1">
              <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📊 Win Rate Trend (rolling 10 trades)</p>
              <div className="flex items-end gap-0.5 h-12">
                {learning.win_rate_trend.map((pt, i) => {
                  const h = Math.max((pt.win_rate / 100) * 100, 4);
                  const cls = pt.win_rate >= TARGET_WIN_RATE ? "bg-green-500" : pt.win_rate >= 50 ? "bg-yellow-400" : "bg-red-400";
                  return <div key={i} title={`Trade #${pt.trade_n}: ${pt.win_rate}%`} className={`flex-1 min-w-[4px] rounded-t ${cls}`} style={{ height: `${h}%` }} />;
                })}
              </div>
              <div className="flex justify-between text-[9px] text-neutral-400 mt-1">
                <span>0%</span><span className="text-green-600 font-semibold">Target {TARGET_WIN_RATE}%</span><span>100%</span>
              </div>
            </div>
          )});
        }
        if (learning?.monthly_stats && learning.monthly_stats.length > 0) {
          slides.push({ key: "month", label: "🗓 Bulanan", node: (
            <div className="p-1">
              <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">📅 Win Rate Bulanan — per Strategi</p>
                <select value={selectedMonth} onChange={e => setSelectedMonth(e.target.value)}
                  className="text-xs border border-neutral-200 rounded-lg px-2 py-1 bg-white text-neutral-700 focus:outline-none">
                  <option value="all">Semua bulan</option>
                  {learning.monthly_stats.map(m => <option key={m.month} value={m.month}>{fmtMonth(m.month)}</option>)}
                </select>
              </div>
              <div className="space-y-3">
                {learning.monthly_stats.filter(m => selectedMonth === "all" || m.month === selectedMonth).map(m => (
                  <div key={m.month} className={`rounded-xl p-3 ${selectedMonth === m.month ? "bg-teal-50 border border-teal-200" : "bg-neutral-50"}`}>
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-xs font-bold text-neutral-700">{fmtMonth(m.month)}</p>
                      <div className="flex gap-3 text-[10px] text-neutral-500">
                        <span>Pre: {m.agent1.wins}/{m.agent1.total}</span>
                        <span>Acc: {m.agent2.wins}/{m.agent2.total}</span>
                        {m.agent3 && <span>Momo: {m.agent3.wins}/{m.agent3.total}</span>}
                        {m.bigmover && <span>BM: {m.bigmover.wins}/{m.bigmover.total}</span>}
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <WinRateBar rate={m.agent1.win_rate} label={`🎯 Pre-Gainer: ${m.agent1.win_rate.toFixed(0)}%`} />
                      <WinRateBar rate={m.agent2.win_rate} label={`📦 Accumulation: ${m.agent2.win_rate.toFixed(0)}%`} />
                      {m.agent3 && <WinRateBar rate={m.agent3.win_rate} label={`🔥 Momentum: ${m.agent3.win_rate.toFixed(0)}%`} />}
                      {/* PLAN_v13 P3 — line ke-4 Big Mover (backend sudah kirim, dulu tak dirender) */}
                      {m.bigmover && <WinRateBar rate={m.bigmover.win_rate} label={`💥 Big Mover: ${m.bigmover.win_rate.toFixed(0)}%`} />}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )});
        }
        return slides.length > 0 ? <ChartCarousel slides={slides} /> : null;
      })()}

      {/* Position sizing info — PLAN_v12 P2-B4: Auto-Open dibuang (beda per-agent, ada di kartu agent) */}
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4">
        <p className="text-xs font-bold text-amber-700 uppercase tracking-wider mb-2">💡 Logika Position Sizing (real-wallet + portfolio heat)</p>
        <div className="grid grid-cols-3 gap-3 text-center">
          {[
            { label: "Modal Awal",   value: `$${startingBalance.toLocaleString()}`,          sub: "paper balance"   },
            { label: "Risk/Trade",   value: `$${riskDollar.toFixed(0)} (1%)`,                sub: "fixed per trade" },
            { label: "R:R Minimum",  value: "1 : 3",                                         sub: `win $${(riskDollar * 3).toFixed(0)}, lose $${riskDollar.toFixed(0)}` },
          ].map(x => (
            <div key={x.label} className="bg-white/60 rounded-xl p-2.5">
              <p className="text-[10px] text-amber-600 font-semibold">{x.label}</p>
              <p className="text-base font-black text-neutral-800">{x.value}</p>
              <p className="text-[9px] text-neutral-400">{x.sub}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Live indicator */}
      <div className="flex items-center justify-end gap-2">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-blue-50 border border-blue-200">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-[10px] font-bold text-blue-700">LIVE</span>
          <span className="text-[10px] text-blue-600 tabular-nums">{countdown}s</span>
        </div>
        {lastUpdated && <p className="text-[10px] text-neutral-400">{lastUpdated.toLocaleTimeString()}</p>}
        <button onClick={onRefresh} disabled={loading} className="text-xs text-teal-600 hover:text-teal-500 font-semibold disabled:opacity-40">
          {loading ? "..." : "↺"}
        </button>
      </div>

      {/* DB History */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-neutral-100 bg-neutral-50">
          <h3 className="font-bold text-sm text-neutral-700">🗄 Riwayat Database — Futures Agents 1, 2, 3</h3>
          <p className="text-[10px] text-neutral-400 mt-0.5">Semua trade · search simbol · pagination · alasan tutup posisi lengkap</p>
        </div>
        <div className="p-4">
          <DBHistoryTable
            defaultStyle="futures"
            hideStyleTabs={false}
            compact={true}
            reasonScope="futures"
            styleOptions={[
              { key: "futures",        label: "Semua" },
              { key: "agentic",        label: "🧠 Agentic" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
