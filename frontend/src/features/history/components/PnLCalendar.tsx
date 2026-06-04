"use client";

import { useMemo, useState } from "react";

export interface DayPnL {
  date: string;   // "YYYY-MM-DD"
  pnl: number;    // net PnL in R units (e.g. +3.0 = +3R)
  wins: number;
  losses: number;
  trades: number;
}

interface PnLCalendarProps {
  days: DayPnL[];
  totalPnl: number;
}

type Period = "7d" | "1w" | "1m";

const WEEKDAYS = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"];

function pnlColor(pnl: number, trades: number): string {
  if (trades === 0) return "bg-neutral-100 text-neutral-300";
  if (pnl > 5)  return "bg-green-600 text-white";
  if (pnl > 2)  return "bg-green-500 text-white";
  if (pnl > 0)  return "bg-green-400 text-white";
  if (pnl < -3) return "bg-red-600 text-white";
  if (pnl < -1) return "bg-red-500 text-white";
  return "bg-red-400 text-white";
}

function pnlBorder(pnl: number, trades: number): string {
  if (trades === 0) return "border-neutral-200";
  if (pnl > 0) return "border-green-300";
  return "border-red-300";
}

function fmt(n: number): string {
  return (n >= 0 ? "+" : "") + n.toFixed(1) + "R";
}

function dayLabel(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return d.getDate().toString();
}

function monthLabel(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("id-ID", { month: "short" });
}

export function PnLCalendar({ days, totalPnl }: PnLCalendarProps) {
  const [period, setPeriod] = useState<Period>("1m");

  const filtered = useMemo(() => {
    const n = period === "7d" ? 7 : period === "1w" ? 7 : 30;
    return days.slice(-n);
  }, [days, period]);

  // For 1M: build full calendar grid (Mon-Sun rows)
  const calendarGrid = useMemo(() => {
    if (period !== "1m") return null;
    if (!filtered.length) return null;

    const first = new Date(filtered[0].date + "T00:00:00");
    // Pad to Monday of the first week
    const startDow = (first.getDay() + 6) % 7; // 0=Mon
    const paddedStart: (DayPnL | null)[] = Array(startDow).fill(null);
    const allCells: (DayPnL | null)[] = [...paddedStart, ...filtered];
    // Pad end to complete last row
    const rem = allCells.length % 7;
    if (rem > 0) for (let i = 0; i < 7 - rem; i++) allCells.push(null);

    const weeks: (DayPnL | null)[][] = [];
    for (let i = 0; i < allCells.length; i += 7) {
      weeks.push(allCells.slice(i, i + 7));
    }
    return weeks;
  }, [filtered, period]);

  // Summary stats for the filtered period
  const summary = useMemo(() => {
    const activeDays = filtered.filter(d => d.trades > 0);
    const profitDays = activeDays.filter(d => d.pnl > 0).length;
    const lossDays   = activeDays.filter(d => d.pnl < 0).length;
    const pnl        = filtered.reduce((s, d) => s + d.pnl, 0);
    const wins       = filtered.reduce((s, d) => s + d.wins, 0);
    const losses     = filtered.reduce((s, d) => s + d.losses, 0);
    return { activeDays: activeDays.length, profitDays, lossDays, pnl, wins, losses };
  }, [filtered]);

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <p className="text-sm font-bold text-neutral-800">📅 PnL Kalender</p>
          <p className="text-xs text-neutral-500 mt-0.5">
            Simulasi 1% risk · setiap hari tertutup (TP/SL) dicatat
          </p>
        </div>

        {/* Period toggle */}
        <div className="flex bg-neutral-100 rounded-lg p-0.5 gap-0.5">
          {(["7d", "1w", "1m"] as Period[]).map(p => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                period === p
                  ? "bg-white shadow text-neutral-900"
                  : "text-neutral-500 hover:text-neutral-700"
              }`}>
              {p === "7d" ? "7 Hari" : p === "1w" ? "1 Minggu" : "1 Bulan"}
            </button>
          ))}
        </div>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {[
          { label: "Total PnL", value: fmt(summary.pnl), color: summary.pnl >= 0 ? "text-green-600" : "text-red-500" },
          { label: "Profit Days", value: `${summary.profitDays} hari`, color: "text-green-600" },
          { label: "Loss Days",   value: `${summary.lossDays} hari`,   color: "text-red-500"   },
          { label: "TP / SL",     value: `${summary.wins} / ${summary.losses}`, color: "text-neutral-700" },
        ].map(s => (
          <div key={s.label} className="bg-neutral-50 border border-neutral-200 rounded-xl px-3 py-2">
            <p className="text-[10px] text-neutral-500 font-semibold uppercase tracking-wide mb-0.5">{s.label}</p>
            <p className={`text-base font-bold ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* ── Calendar grid (1M) ── */}
      {calendarGrid && (
        <div className="overflow-x-auto">
          {/* Weekday headers */}
          <div className="grid grid-cols-7 gap-1 mb-1 min-w-[420px]">
            {WEEKDAYS.map(w => (
              <div key={w} className="text-center text-[10px] font-bold text-neutral-400 py-1">{w}</div>
            ))}
          </div>
          {/* Weeks */}
          <div className="space-y-1 min-w-[420px]">
            {calendarGrid.map((week, wi) => {
              // Show month label at start of new month
              const firstDay = week.find(d => d && d.date);
              return (
                <div key={wi} className="grid grid-cols-7 gap-1">
                  {week.map((day, di) => {
                    if (!day) return <div key={di} className="rounded-lg h-14" />;
                    const isToday = day.date === new Date().toISOString().split("T")[0];
                    return (
                      <div key={di} title={`${day.date} | PnL: ${fmt(day.pnl)} | ${day.wins}W ${day.losses}L`}
                        className={`relative rounded-lg border h-14 flex flex-col items-center justify-center transition-all cursor-default hover:brightness-95 ${pnlColor(day.pnl, day.trades)} ${pnlBorder(day.pnl, day.trades)} ${isToday ? "ring-2 ring-teal-400 ring-offset-1" : ""}`}>
                        {/* Day number */}
                        <span className="text-[10px] font-bold leading-tight opacity-80">
                          {dayLabel(day.date)}
                        </span>
                        {/* PnL */}
                        {day.trades > 0 ? (
                          <span className="text-[10px] font-bold leading-tight">{fmt(day.pnl)}</span>
                        ) : (
                          <span className="text-[9px] opacity-40">—</span>
                        )}
                        {/* Trade count dot */}
                        {day.trades > 0 && (
                          <span className="text-[8px] opacity-70 leading-tight">{day.trades}t</span>
                        )}
                        {/* Month label on 1st */}
                        {dayLabel(day.date) === "1" && (
                          <span className="absolute -top-3 left-0 text-[9px] text-neutral-400 font-bold">
                            {monthLabel(day.date)}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Row view (7D / 1W) ── */}
      {!calendarGrid && (
        <div className="overflow-x-auto">
          <div className="flex gap-2 min-w-fit">
            {filtered.map(day => {
              const isToday = day.date === new Date().toISOString().split("T")[0];
              const d = new Date(day.date + "T00:00:00");
              const label = d.toLocaleDateString("id-ID", { weekday: "short", day: "numeric", month: "short" });
              return (
                <div key={day.date} title={`${day.date} | PnL: ${fmt(day.pnl)} | ${day.wins}W ${day.losses}L`}
                  className={`rounded-xl border flex flex-col items-center justify-center px-3 py-4 min-w-[90px] gap-1 cursor-default hover:brightness-95 transition-all ${pnlColor(day.pnl, day.trades)} ${pnlBorder(day.pnl, day.trades)} ${isToday ? "ring-2 ring-teal-400 ring-offset-1" : ""}`}>
                  <span className="text-[10px] font-semibold opacity-80 text-center">{label}</span>
                  {day.trades > 0 ? (
                    <>
                      <span className="text-lg font-black leading-tight">{fmt(day.pnl)}</span>
                      <span className="text-[10px] opacity-80">{day.wins}W · {day.losses}L · {day.trades}t</span>
                    </>
                  ) : (
                    <span className="text-sm opacity-40 font-bold">—</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] text-neutral-500 flex-wrap">
        <span className="font-semibold">Legend:</span>
        {[
          { bg: "bg-green-600", label: "> +5R" },
          { bg: "bg-green-400", label: "+1 s/d +5R" },
          { bg: "bg-red-400",   label: "-1 s/d -3R" },
          { bg: "bg-red-600",   label: "< -3R" },
          { bg: "bg-neutral-200", label: "No trade" },
        ].map(l => (
          <span key={l.label} className="flex items-center gap-1">
            <span className={`w-3 h-3 rounded ${l.bg}`} />
            {l.label}
          </span>
        ))}
      </div>
    </div>
  );
}
