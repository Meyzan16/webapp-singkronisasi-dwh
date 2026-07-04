"use client";
import type { GateState } from "./types";

export function GateBanner({ gate }: { gate: GateState | undefined }) {
  if (!gate?.active) return null;

  const isCB  = gate.gate_type === "circuit_breaker";
  const isRAR = gate.gate_type === "rar";
  const isOverride = gate.gate_type === "override";

  const cfg = isCB
    ? { bg: "bg-red-50 border-red-300",         icon: "⛔", title: "Circuit Breaker Aktif",   textCls: "text-red-700" }
    : isRAR
    ? { bg: "bg-orange-50 border-orange-300",   icon: "⚠️", title: "RAR Gate Aktif",           textCls: "text-orange-700" }
    : { bg: "bg-yellow-50 border-yellow-300",   icon: "🔒", title: "Gate Manual (Override)",   textCls: "text-yellow-800" };

  return (
    <div className={`border rounded-2xl p-4 ${cfg.bg}`}>
      <div className="flex items-start gap-3">
        <span className="text-2xl leading-none mt-0.5">{cfg.icon}</span>
        <div className="flex-1 min-w-0">
          <p className={`font-black text-sm mb-1 ${cfg.textCls}`}>{cfg.title}</p>
          <p className={`text-xs leading-relaxed ${cfg.textCls} opacity-90`}>{gate.reason}</p>
          {!isOverride && (
            <div className="flex gap-4 mt-2 text-xs flex-wrap">
              <span className={cfg.textCls}>
                DD dari peak: <strong className={isCB ? "text-red-700" : ""}>{gate.drawdown_pct?.toFixed(1) ?? "—"}%</strong>
                <span className="opacity-60 ml-1">(batas {gate.dd_threshold}%)</span>
              </span>
              {gate.n_trades >= 5 && (
                <span className={cfg.textCls}>
                  Sharpe: <strong className={isRAR ? "text-orange-700" : ""}>{gate.rar?.toFixed(3) ?? "—"}</strong>
                  <span className="opacity-60 ml-1">(batas {gate.rar_threshold})</span>
                </span>
              )}
              <span className="opacity-60 text-neutral-500">{gate.n_trades} trade tertutup</span>
            </div>
          )}
          {/* PLAN_v11 P1 — jawab "kapan berakhir": Sharpe rolling + probe schedule */}
          {isRAR && (
            <div className="mt-2 text-[11px] text-orange-800 bg-orange-100/60 rounded-lg px-2.5 py-1.5 leading-relaxed">
              <strong>Kapan berakhir?</strong> Sharpe dihitung dari{" "}
              <strong>{gate.rar_window ?? 20} trade terakhir</strong> (rolling) — gate akan
              terbuka begitu performa terbaru membaik. Untuk memecah kebuntuan, agent
              membuka <strong>1 posisi probe ½-risk</strong>{" "}
              {gate.probe_allowed
                ? "sekarang (jatuh tempo)."
                : gate.next_probe_in_sec != null
                ? `dalam ~${Math.ceil((gate.next_probe_in_sec ?? 0) / 60)} menit.`
                : "berkala."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
