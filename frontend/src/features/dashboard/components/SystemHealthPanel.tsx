"use client";
import { StatusDot } from "@/components/ui/trading-badges";
import type { Health, BinanceStatus, AgentState } from "@/types/health";

function AgentRow({ label, sub, ok, cycle, err, color = "text-green-600" }: {
  label: string; sub: string; ok: boolean; cycle?: number; err?: string | null; color?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-neutral-50 last:border-0">
      <div className="min-w-0">
        <p className="text-xs text-neutral-700 font-semibold">{label}</p>
        <p className="text-[10px] text-neutral-400 truncate">{sub}</p>
      </div>
      <div className="text-right shrink-0 ml-3">
        <span className={`text-[10px] font-bold flex items-center gap-1 justify-end ${ok ? color : "text-neutral-400"}`}>
          <StatusDot ok={ok} />
          {ok ? "Running" : "—"}
        </span>
        {cycle != null && <p className="text-[9px] text-neutral-400">{cycle}x siklus</p>}
        {err && <p className="text-[9px] text-red-400 truncate max-w-[100px]" title={err}>⚠ error</p>}
      </div>
    </div>
  );
}

function BinanceApiRow({ label, ok, latency, weightPct, weightUsed, bannedUntil, error, emergencyThreshold, warningThreshold }: {
  label: string; ok: boolean; latency: number | null; weightPct: number;
  weightUsed: number; bannedUntil: number | null; error: string | null;
  emergencyThreshold?: number; warningThreshold?: number;
}) {
  const banned    = bannedUntil != null;
  const emergency = emergencyThreshold != null && weightUsed > emergencyThreshold;
  const hot       = weightPct > 70 || (warningThreshold != null && weightUsed > warningThreshold);
  const warn      = weightPct > 40 && !hot;
  const barColor  = banned ? "bg-red-500" : emergency ? "bg-red-500" : hot ? "bg-orange-500" : warn ? "bg-yellow-400" : "bg-green-400";
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-neutral-700 font-semibold">{label}</span>
        <div className="flex items-center gap-1.5">
          {emergency && <span className="text-[9px] font-bold bg-red-100 text-red-700 px-1 py-0.5 rounded">EMERGENCY</span>}
          {!emergency && hot && warningThreshold != null && weightUsed > warningThreshold && (
            <span className="text-[9px] font-bold bg-orange-100 text-orange-700 px-1 py-0.5 rounded">WARN</span>
          )}
          <span className={`text-[10px] font-bold flex items-center gap-1 ${banned ? "text-red-600" : ok ? "text-green-600" : "text-red-500"}`}>
            <StatusDot ok={ok && !banned} />
            {banned ? "BANNED" : ok ? `OK${latency != null ? ` · ${latency}ms` : ""}` : "Down"}
          </span>
        </div>
      </div>
      {!banned && (
        <div className="flex items-center gap-1.5">
          <div className="flex-1 bg-neutral-100 rounded-full h-1.5 overflow-hidden">
            <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${Math.min(weightPct, 100)}%` }} />
          </div>
          <span className={`text-[10px] tabular-nums font-semibold shrink-0 ${hot ? "text-orange-600" : warn ? "text-yellow-600" : "text-neutral-400"}`}>
            {weightPct.toFixed(0)}%
          </span>
        </div>
      )}
      {banned && bannedUntil != null && (
        <p className="text-[10px] text-red-500 font-semibold mt-0.5">
          ⛔ sampai {new Date(bannedUntil * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}
        </p>
      )}
      {!banned && error && <p className="text-[10px] text-orange-500 truncate mt-0.5" title={error}>⚠ {error}</p>}
    </div>
  );
}

export function SystemHealthPanel({ health, binance, closedToday, futResultsA2, futResultsA3 }: {
  health: Health | null;
  binance: BinanceStatus | null;
  closedToday?: number;
  futResultsA2?: number;
  futResultsA3?: number;
}) {
  return (
    <div className="bg-white rounded-2xl border border-neutral-200 p-4">
      <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">⚙️ System Health</p>

      {/* Backend + DB */}
      <div className="space-y-1.5 mb-3 pb-3 border-b border-neutral-100">
        {[
          { label: "Backend API", ok: !!health },
          { label: "Database",    ok: health?.db === "ok" },
        ].map(row => (
          <div key={row.label} className="flex items-center justify-between py-1 rounded-lg">
            <span className="text-xs text-neutral-600 font-medium">{row.label}</span>
            <span className={`text-[10px] font-bold flex items-center gap-1 ${row.ok ? "text-green-600" : "text-neutral-400"}`}>
              <StatusDot ok={row.ok} />
              {row.ok ? "Online" : "—"}
            </span>
          </div>
        ))}
      </div>

      {/* Binance API */}
      <p className="text-[9px] font-black text-yellow-600 uppercase tracking-widest mb-1.5">🔗 Binance API</p>
      <div className="space-y-2 mb-3 pb-3 border-b border-neutral-100">
        <BinanceApiRow label="Spot API"
          ok={binance?.spot_ok ?? false} latency={binance?.spot_latency_ms ?? null}
          weightPct={binance?.spot_weight_pct ?? 0} weightUsed={binance?.spot_weight_used ?? 0}
          bannedUntil={binance?.spot_banned_until ?? null} error={binance?.spot_error ?? null} />
        <BinanceApiRow label="Futures API"
          ok={binance?.futures_ok ?? false} latency={binance?.futures_latency_ms ?? null}
          weightPct={binance?.futures_weight_pct ?? 0} weightUsed={binance?.futures_weight_used ?? 0}
          bannedUntil={binance?.futures_banned_until ?? null} error={binance?.futures_error ?? null}
          warningThreshold={1800} emergencyThreshold={2100} />
        {!binance && <p className="text-[10px] text-neutral-400 italic">Memuat status Binance...</p>}
      </div>

      {/* Spot Agents */}
      <p className="text-[9px] font-black text-teal-600 uppercase tracking-widest mb-1.5">🎯 Spot</p>
      <div className="space-y-1.5 mb-3 pb-3 border-b border-neutral-100">
        <AgentRow label="Spot Opp Scanner" sub={`Scans 100 pairs tiap ${health?.spot_scanner?.interval_minutes ?? 3}m`}
          ok={!!health?.spot_scanner?.running} cycle={health?.spot_scanner?.cycle_count} err={health?.spot_scanner?.last_error} color="text-green-600" />
        <AgentRow label="Spot Position Monitor" sub="Monitor TP/SL posisi spot"
          ok={!!health?.spot_monitor?.running} cycle={health?.spot_monitor?.cycle_count} err={health?.spot_monitor?.last_error} color="text-green-600" />
      </div>

      {/* Futures Agents */}
      <p className="text-[9px] font-black text-blue-600 uppercase tracking-widest mb-1.5">⚡ Futures</p>
      <div className="space-y-1.5">
        <AgentRow label="Futures Scanner — Pre-Gainer" sub="Funding · OI · Liquidation · S/R"
          ok={!!health?.futures_scanner?.running} cycle={health?.futures_scanner?.cycle_count} err={health?.futures_scanner?.last_error} color="text-blue-600" />
        <AgentRow label="Futures Scanner — Accumulation"
          sub={`Wyckoff · Trend · Pattern · Trigger${futResultsA2 != null ? ` · ${futResultsA2} sinyal` : ""}`}
          ok={!!health?.futures_scanner?.running} color="text-blue-600" />
        <AgentRow label="Futures Scanner — Momentum"
          sub={`Breakout · Momentum · Trigger${futResultsA3 != null ? ` · ${futResultsA3} sinyal` : ""}`}
          ok={!!health?.futures_scanner?.running} color="text-blue-600" />
        <AgentRow label="Futures Position Monitor" sub="Monitor TP/SL posisi futures"
          ok={!!health?.futures_monitor?.running} cycle={health?.futures_monitor?.cycle_count} err={health?.futures_monitor?.last_error} color="text-blue-600" />
        <AgentRow label="Weight Updater" sub="Adaptive learning — bobot sinyal"
          ok={!!health?.weight_updater && !health.weight_updater.last_error} err={health?.weight_updater?.last_error} color="text-blue-600" />
      </div>

      {closedToday != null && (
        <div className="mt-3 pt-3 border-t border-neutral-100 flex items-center justify-between text-[10px] text-neutral-400">
          <span>Monitor tertutup hari ini:</span>
          <span className="font-bold text-neutral-600">{closedToday} trades</span>
        </div>
      )}
    </div>
  );
}
