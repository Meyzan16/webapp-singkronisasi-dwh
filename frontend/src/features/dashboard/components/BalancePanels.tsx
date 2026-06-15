"use client";
import Link from "next/link";
import { MiniEquityChart } from "@/components/ui/stat-card";

interface BalanceRow { label: string; value: string; valueClass?: string; extra?: React.ReactNode }
interface StatItem   { label: string; val: string; color: string }

function BalanceRowItem({ label, value, valueClass, extra }: BalanceRow) {
  return (
    <div className="flex justify-between">
      <span className="text-neutral-500">{label}{extra}</span>
      <span className={`font-semibold text-neutral-800 ${valueClass ?? ""}`}>{value}</span>
    </div>
  );
}

function StatMini({ stats }: { stats: StatItem[] }) {
  return (
    <div className={`grid grid-cols-4 gap-1.5 mt-3`}>
      {stats.map(s => (
        <div key={s.label} className="text-center bg-neutral-50 rounded-xl py-2">
          <p className={`text-sm font-black ${s.color}`}>{s.val}</p>
          <p className="text-[9px] text-neutral-400">{s.label}</p>
        </div>
      ))}
    </div>
  );
}

export function SpotBalancePanel({ balance, initial, unrealizedPnl, spotBal, oppOpen, oppClosedAll, equityPoints, winRate }: {
  balance: number;
  initial: number;
  unrealizedPnl: number;
  spotBal: { balance: number; available: number; locked_margin: number; realized_pnl: number; open_positions: number } | null;
  oppOpen: { id: number }[];
  oppClosedAll: { status: string }[];
  equityPoints: { balance: number; win: boolean }[];
  winRate: number;
}) {
  const pnl = balance - initial;
  const wins  = oppClosedAll.filter(p => p.status === "tp").length;
  const losses = oppClosedAll.filter(p => p.status === "sl").length;
  const denom = oppClosedAll.filter(p => p.status === "tp" || p.status === "sl").length;

  return (
    <div className="bg-white rounded-2xl border border-neutral-200 p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">🎯 Spot Balance</p>
        <Link href="/history" className="text-[10px] text-teal-600 hover:underline">detail →</Link>
      </div>
      <div className="flex items-baseline gap-2 mb-3">
        <span className={`text-2xl font-black ${balance >= initial ? "text-green-600" : "text-red-500"}`}>${balance.toFixed(2)}</span>
        <span className={`text-xs font-bold ${pnl >= 0 ? "text-green-500" : "text-red-400"}`}>
          {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
        </span>
      </div>
      <div className="space-y-1.5 text-[11px]">
        <BalanceRowItem label="Wallet Balance" value={`$${(spotBal?.balance ?? balance).toFixed(2)}`} />
        <BalanceRowItem
          label="Unrealized PnL"
          extra={<span className="ml-1 text-[9px] bg-blue-50 text-blue-500 border border-blue-200 px-1 py-px rounded">live</span>}
          value={`${unrealizedPnl >= 0 ? "+" : ""}$${unrealizedPnl.toFixed(2)}`}
          valueClass={unrealizedPnl >= 0 ? "!text-green-600" : "!text-red-500"}
        />
        <div className="flex justify-between font-bold border-t border-neutral-100 pt-1.5">
          <span className="text-neutral-700">Margin Balance</span>
          <span className="text-neutral-900">${((spotBal?.balance ?? balance) + unrealizedPnl).toFixed(2)}</span>
        </div>
        <BalanceRowItem label="Available" value={`$${(spotBal?.available ?? 0).toFixed(2)}`} />
        <BalanceRowItem label={`In Order (${spotBal?.open_positions ?? oppOpen.length})`} value={`$${(spotBal?.locked_margin ?? 0).toFixed(2)}`} />
        <div className="flex justify-between border-t border-neutral-100 pt-1.5">
          <span className="text-neutral-500">Realized PnL</span>
          <span className={`font-semibold ${(spotBal?.realized_pnl ?? pnl) >= 0 ? "text-green-600" : "text-red-500"}`}>
            {(spotBal?.realized_pnl ?? pnl) >= 0 ? "+" : ""}${(spotBal?.realized_pnl ?? pnl).toFixed(2)}
          </span>
        </div>
      </div>
      {equityPoints.length > 1 && <div className="mt-3"><MiniEquityChart points={equityPoints} /></div>}
      <StatMini stats={[
        { label: "Open",  val: String(oppOpen.length), color: "text-blue-600" },
        { label: "Win",   val: String(wins),           color: "text-green-600" },
        { label: "Loss",  val: String(losses),         color: "text-red-500" },
        { label: "WR",    val: denom > 0 ? `${winRate.toFixed(0)}%` : "—", color: winRate >= 50 ? "text-green-600" : "text-red-500" },
      ]} />
    </div>
  );
}

export function FuturesBalancePanel({ balance, initial, unrealizedPnl, futOpen, learning }: {
  balance: number;
  initial: number;
  unrealizedPnl: number;
  futOpen: { id: number }[];
  learning: {
    balance: { total_pnl: number };
    equity_points: { balance: number; win: boolean }[];
    overall: { open: number; wins: number; losses: number; closed: number };
    regime?: string;
    overall: { win_rate: number };
  } | null;
}) {
  const pnl = balance - initial;
  const winRate = learning?.overall.win_rate ?? 0;

  return (
    <div className="bg-white rounded-2xl border border-neutral-200 p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">⚡ Futures Balance</p>
        <Link href="/history" className="text-[10px] text-blue-600 hover:underline">detail →</Link>
      </div>
      <div className="flex items-baseline gap-2 mb-3">
        <span className={`text-2xl font-black ${balance >= initial ? "text-green-600" : "text-red-500"}`}>${balance.toFixed(2)}</span>
        <span className={`text-xs font-bold ${pnl >= 0 ? "text-green-500" : "text-red-400"}`}>{pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}</span>
      </div>
      <div className="space-y-1.5 text-[11px]">
        <BalanceRowItem label="Wallet Balance" value={`$${balance.toFixed(2)}`} />
        <BalanceRowItem
          label="Unrealized PnL"
          extra={<span className="ml-1 text-[9px] bg-blue-50 text-blue-500 border border-blue-200 px-1 py-px rounded">live</span>}
          value={futOpen.length > 0 ? `${unrealizedPnl >= 0 ? "+" : ""}$${unrealizedPnl.toFixed(2)}` : "—"}
          valueClass={unrealizedPnl >= 0 ? "!text-green-600" : "!text-red-500"}
        />
        <div className="flex justify-between font-bold border-t border-neutral-100 pt-1.5">
          <span className="text-neutral-700">Margin Balance</span>
          <span className="text-neutral-900">${(balance + (futOpen.length > 0 ? unrealizedPnl : 0)).toFixed(2)}</span>
        </div>
        <div className="flex justify-between border-t border-neutral-100 pt-1.5">
          <span className="text-neutral-500">Realized PnL</span>
          <span className={`font-semibold ${(learning?.balance.total_pnl ?? 0) >= 0 ? "text-green-600" : "text-red-500"}`}>
            {learning?.balance.total_pnl != null
              ? `${learning.balance.total_pnl >= 0 ? "+" : ""}$${learning.balance.total_pnl.toFixed(2)}`
              : "—"}
          </span>
        </div>
      </div>
      {learning?.equity_points && learning.equity_points.length > 1 && (
        <div className="mt-3"><MiniEquityChart points={learning.equity_points} /></div>
      )}
      <StatMini stats={[
        { label: "Open",  val: String(learning?.overall.open   ?? futOpen.length), color: "text-blue-600"  },
        { label: "Win",   val: String(learning?.overall.wins   ?? 0),              color: "text-green-600" },
        { label: "Loss",  val: String(learning?.overall.losses ?? 0),              color: "text-red-500"   },
        { label: "WR",    val: learning && learning.overall.closed > 0 ? `${winRate.toFixed(0)}%` : "—", color: winRate >= 50 ? "text-green-600" : "text-red-500" },
      ]} />
      {learning?.regime && (
        <div className="mt-2 flex items-center gap-1.5">
          <span className="text-[10px] text-neutral-400">Regime:</span>
          <span className="text-[10px] font-bold bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full border border-blue-200 capitalize">{learning.regime}</span>
        </div>
      )}
    </div>
  );
}
