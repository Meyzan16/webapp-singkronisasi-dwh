"use client";
import { useMemo, useState } from "react";
import type { OppPosition } from "./OppSpotTypes";

// §8.1: SEMUA tanggal pakai komponen LOKAL (WIB) — bukan toISOString (UTC).
// Trade yang close 00:00–06:59 WIB harus tercatat di hari WIB yang benar.
export function localDayKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

interface PnlCalendarProps {
  calendarMap:  Map<string, number>;   // localDayKey → P&L $ hari itu
  closedTrades: OppPosition[];         // untuk detail per-hari saat sel diklik
  balance:      number;                // §8.4: threshold warna relatif ke balance
}

const WEEKDAYS = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"];
const MONTHS = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember",
];

export function PnlCalendar({ calendarMap, closedTrades, balance }: PnlCalendarProps) {
  const today = new Date();
  const [viewYear, setViewYear]   = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth());
  const [selectedDay, setSelected] = useState<string | null>(null);

  const todayKey = localDayKey(today);
  const isCurrentMonth =
    viewYear === today.getFullYear() && viewMonth === today.getMonth();

  // §8.4: gradasi relatif — ±2% dari balance, bukan ±$5 hardcode
  const t2 = Math.max(2.0, balance * 0.02);

  const cellBg = (pnl: number | undefined): string => {
    if (pnl == null)  return "bg-neutral-100";
    if (pnl >= t2)    return "bg-green-600";
    if (pnl >= 0)     return "bg-green-300";
    if (pnl > -t2)    return "bg-red-300";
    return "bg-red-600";
  };

  const monthDays = useMemo(() => {
    const first = new Date(viewYear, viewMonth, 1);
    const count = new Date(viewYear, viewMonth + 1, 0).getDate();
    const pad   = (first.getDay() + 6) % 7; // Senin = 0
    const days  = Array.from({ length: count }, (_, i) => {
      const d = new Date(viewYear, viewMonth, i + 1);
      const key = localDayKey(d);
      return { key, dayNum: i + 1, pnl: calendarMap.get(key) };
    });
    return { pad, days };
  }, [viewYear, viewMonth, calendarMap]);

  const monthSummary = useMemo(() => {
    const total = monthDays.days.reduce((s, d) => s + (d.pnl ?? 0), 0);
    const profit = monthDays.days.filter(d => (d.pnl ?? 0) > 0 && d.pnl != null).length;
    const loss   = monthDays.days.filter(d => (d.pnl ?? 0) < 0).length;
    const traded = monthDays.days.filter(d => d.pnl != null).length;
    return { total, profit, loss, traded };
  }, [monthDays]);

  const todayPnl = calendarMap.get(todayKey);

  const dayTrades = useMemo(() => {
    if (!selectedDay) return [];
    return closedTrades
      .filter(p => p.closed_at && localDayKey(new Date(p.closed_at * 1000)) === selectedDay)
      .sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0));
  }, [selectedDay, closedTrades]);

  const navMonth = (delta: number) => {
    setSelected(null);
    const d = new Date(viewYear, viewMonth + delta, 1);
    setViewYear(d.getFullYear());
    setViewMonth(d.getMonth());
  };

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      {/* Header: nav bulan + summary */}
      <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div>
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">
            📅 P&L Kalender <span className="normal-case text-neutral-300">(waktu lokal WIB)</span>
          </p>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            {todayPnl != null ? (
              <span className="text-xs">
                Hari ini:&nbsp;
                <strong className={todayPnl >= 0 ? "text-green-600" : "text-red-500"}>
                  {todayPnl >= 0 ? "+" : ""}${todayPnl.toFixed(2)}
                </strong>
              </span>
            ) : (
              <span className="text-xs text-neutral-400">Hari ini: no trade</span>
            )}
            <span className="text-neutral-300">·</span>
            <span className="text-xs">
              {MONTHS[viewMonth]}:&nbsp;
              <strong className={monthSummary.total >= 0 ? "text-green-600" : "text-red-500"}>
                {monthSummary.total >= 0 ? "+" : ""}${monthSummary.total.toFixed(2)}
              </strong>
            </span>
            <span className="text-[10px] text-neutral-400">
              ({monthSummary.profit}🟢 {monthSummary.loss}🔴 dari {monthSummary.traded} hari trading)
            </span>
          </div>
        </div>

        {/* Navigasi bulan ala Binance */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => navMonth(-1)}
            className="text-sm font-bold w-7 h-7 rounded-lg border border-neutral-200 text-neutral-500 hover:border-teal-300 hover:text-teal-600"
          >
            ‹
          </button>
          <span className="text-xs font-bold text-neutral-700 px-2 tabular-nums min-w-[110px] text-center">
            {MONTHS[viewMonth]} {viewYear}
          </span>
          <button
            onClick={() => navMonth(1)}
            className="text-sm font-bold w-7 h-7 rounded-lg border border-neutral-200 text-neutral-500 hover:border-teal-300 hover:text-teal-600"
          >
            ›
          </button>
          {!isCurrentMonth && (
            <button
              onClick={() => {
                setViewYear(today.getFullYear());
                setViewMonth(today.getMonth());
                setSelected(null);
              }}
              className="ml-1 text-[10px] font-bold px-2 py-1.5 rounded-lg bg-teal-500 text-white"
            >
              Bulan ini
            </button>
          )}
        </div>
      </div>

      {/* Header hari */}
      <div className="grid grid-cols-7 gap-1 mb-1">
        {WEEKDAYS.map(day => (
          <div key={day} className="text-[9px] text-neutral-400 text-center font-semibold">
            {day}
          </div>
        ))}
      </div>

      {/* Grid bulan penuh — sel berisi tanggal + nominal P&L (ala Binance) */}
      <div className="grid grid-cols-7 gap-1">
        {Array.from({ length: monthDays.pad }, (_, i) => (
          <div key={`pad-${i}`} className="h-12" />
        ))}
        {monthDays.days.map(({ key, dayNum, pnl }) => {
          const isToday    = key === todayKey;
          const isSelected = key === selectedDay;
          const hasPnl     = pnl != null;
          return (
            <button
              key={key}
              onClick={() => setSelected(isSelected ? null : key)}
              title={`${key}: ${hasPnl ? (pnl! >= 0 ? "+" : "") + "$" + pnl!.toFixed(2) : "No trade"}`}
              className={`h-12 rounded-lg flex flex-col items-center justify-center gap-0.5 transition-all ${cellBg(pnl)} ${
                isToday ? "ring-2 ring-teal-500 ring-offset-1" : ""
              } ${isSelected ? "ring-2 ring-blue-500 ring-offset-1 scale-105" : "hover:opacity-80"}`}
            >
              <span className={`text-[10px] font-bold leading-none ${
                hasPnl ? "text-white" : "text-neutral-400"
              } ${isToday ? "underline" : ""}`}>
                {dayNum}
              </span>
              {hasPnl && (
                <span className="text-[8px] font-black text-white leading-none tabular-nums">
                  {pnl! >= 0 ? "+" : ""}{Math.abs(pnl!) >= 100 ? pnl!.toFixed(0) : pnl!.toFixed(2)}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Legend relatif */}
      <div className="flex gap-3 mt-3 text-[9px] text-neutral-400 flex-wrap">
        {[
          { bg: "bg-green-600",   label: `≥ +$${t2.toFixed(0)}` },
          { bg: "bg-green-300",   label: `$0–$${t2.toFixed(0)}` },
          { bg: "bg-neutral-100", label: "No trade" },
          { bg: "bg-red-300",     label: `−$${t2.toFixed(0)}–$0` },
          { bg: "bg-red-600",     label: `≤ −$${t2.toFixed(0)}` },
        ].map(x => (
          <span key={x.label} className="flex items-center gap-1">
            <span className={`w-3 h-3 rounded ${x.bg} inline-block`} /> {x.label}
          </span>
        ))}
        <span className="ml-2 flex items-center gap-1 text-teal-600 font-semibold">
          <span className="w-3 h-3 rounded ring-2 ring-teal-500 inline-block" /> Hari ini
        </span>
        <span className="text-neutral-300 ml-auto">klik tanggal untuk detail</span>
      </div>

      {/* Detail trade per hari (klik tanggal — ala Binance) */}
      {selectedDay && (
        <div className="mt-3 border-t border-neutral-100 pt-3">
          <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-2">
            Trade close pada {selectedDay}
          </p>
          {dayTrades.length === 0 ? (
            <p className="text-xs text-neutral-400">Tidak ada trade close di hari ini.</p>
          ) : (
            <div className="space-y-1">
              {dayTrades.map(p => (
                <div key={p.id} className="flex items-center gap-2 text-xs py-1 border-b border-neutral-50 last:border-0">
                  <span className="font-bold w-20">{p.symbol.replace("USDT", "")}</span>
                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                    p.status === "tp"     ? "bg-green-100 text-green-700" :
                    p.status === "sl"     ? "bg-red-100 text-red-600" :
                                            "bg-neutral-100 text-neutral-500"
                  }`}>
                    {p.status.toUpperCase()}
                  </span>
                  <span className="text-[10px] text-neutral-400">
                    {p.closed_at
                      ? new Date(p.closed_at * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })
                      : ""}
                  </span>
                  <span className={`ml-auto font-black tabular-nums ${
                    (p.pnl_pct ?? 0) >= 0 ? "text-green-600" : "text-red-500"
                  }`}>
                    {(p.pnl_pct ?? 0) >= 0 ? "+" : ""}{(p.pnl_pct ?? 0).toFixed(2)}%
                  </span>
                  {p.pnl_dollar != null && (
                    <span className={`font-bold tabular-nums w-16 text-right ${
                      p.pnl_dollar >= 0 ? "text-green-600" : "text-red-500"
                    }`}>
                      {p.pnl_dollar >= 0 ? "+" : ""}${p.pnl_dollar.toFixed(2)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
