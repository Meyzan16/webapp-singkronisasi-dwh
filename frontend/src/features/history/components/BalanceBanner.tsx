"use client";
import type { ApiBalance, OppStats } from "./OppSpotTypes";

interface BalanceBannerProps {
  stats:      OppStats;
  apiBalance: ApiBalance | null;
  openCount:  number;
  onDeposit:  () => void;
}

export function BalanceBanner({ stats, apiBalance, openCount, onDeposit }: BalanceBannerProps) {
  const balanceColor = stats.currentBalance >= stats.initialBalance
    ? "text-green-500"
    : "text-red-500";

  const minB = Math.min(...stats.equityPoints.map(p => p.balance));
  const maxB = Math.max(...stats.equityPoints.map(p => p.balance));

  return (
    <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white overflow-hidden">
      <div className="p-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">

          {/* Left: balance block */}
          <div>
            <div className="flex items-center gap-2 mb-1">
              <p className="text-xs text-neutral-400 font-semibold uppercase tracking-wider">
                Spot Opportunity
              </p>
              {apiBalance && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-teal-900/60 border border-teal-700/50">
                  <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
                  <span className="text-[9px] font-bold text-teal-400">LIVE</span>
                </span>
              )}
            </div>

            <div className="flex items-baseline gap-2">
              <span className={`text-4xl font-black tabular-nums ${balanceColor}`}>
                ${stats.currentBalance.toFixed(2)}
              </span>
              <span className={`text-sm font-bold ${stats.totalPnl$ >= 0 ? "text-green-400" : "text-red-400"}`}>
                {stats.totalPnl$ >= 0 ? "+" : ""}${stats.totalPnl$.toFixed(2)}
              </span>
            </div>

            <p className="text-xs text-neutral-400 mt-1">
              Modal awal{" "}
              <strong className="text-neutral-200">${stats.initialBalance.toLocaleString()}</strong>
              {" "}· Risk{" "}
              <strong className="text-yellow-300">${stats.riskDollar.toFixed(0)}/trade (1%)</strong>
              {apiBalance && apiBalance.deposited_total > 0 && (
                <span className="ml-2 text-blue-300">
                  · Deposit: +${apiBalance.deposited_total.toFixed(0)}
                </span>
              )}
              {stats.autoOpened > 0 && (
                <span className="ml-2 text-teal-300">· {stats.autoOpened} auto-opened</span>
              )}
            </p>

            {openCount > 0 && (
              <p className="text-xs text-blue-300 mt-1">
                {openCount} posisi terbuka
                {" "}· Risk aktif:{" "}
                <strong className="text-yellow-300">${stats.totalRisk$.toFixed(0)}</strong>
                {" "}· Notional:{" "}
                <strong className={stats.availableBalance$ < 0 ? "text-red-400" : "text-blue-200"}>
                  ${stats.totalNotional$.toFixed(0)}
                </strong>
                {stats.availableBalance$ < 0 && (
                  <span className="text-red-400 font-bold"> ⚠️ melebihi balance!</span>
                )}
              </p>
            )}

            <button
              onClick={onDeposit}
              className="mt-2 text-xs px-3 py-1 rounded-full bg-teal-600/30 border border-teal-500/50 text-teal-300 hover:bg-teal-600/50 transition-colors"
            >
              + Deposit
            </button>
          </div>

          {/* Right: win rate */}
          <div className="text-right">
            <p className={`text-3xl font-black tabular-nums ${stats.winRate >= 50 ? "text-green-400" : "text-red-400"}`}>
              {(stats.tp + stats.sl) > 0 ? `${stats.winRate.toFixed(0)}%` : "—"}
            </p>
            <p className="text-[10px] text-neutral-400 mt-0.5">Win Rate (TP vs SL)</p>
            <p className="text-[10px] text-neutral-500">
              {stats.wins}W · {stats.sl}L
              {stats.manual > 0 && (
                <span className="text-neutral-600"> · {stats.manual} manual</span>
              )}
            </p>
          </div>
        </div>

        {/* Equity mini-chart */}
        {stats.equityPoints.length > 1 && (
          <div className="mt-4">
            <div className="flex items-end gap-0.5 h-10">
              {stats.equityPoints.map((pt, i) => {
                const h = maxB > minB ? ((pt.balance - minB) / (maxB - minB)) * 100 : 50;
                return (
                  <div
                    key={i}
                    title={`#${pt.n} ${pt.symbol} $${pt.balance.toFixed(0)}`}
                    className={`flex-1 min-w-[2px] rounded-t ${
                      i === 0 ? "bg-neutral-600" : pt.win ? "bg-green-500" : "bg-red-500"
                    }`}
                    style={{ height: `${Math.max(h, 4)}%` }}
                  />
                );
              })}
            </div>
            <div className="flex justify-between text-[9px] text-neutral-500 mt-0.5">
              <span>${stats.initialBalance.toLocaleString()} start</span>
              <span className={`font-bold ${balanceColor}`}>
                ${stats.currentBalance.toFixed(0)}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
