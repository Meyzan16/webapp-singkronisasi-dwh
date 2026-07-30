"use client";

import { agentLabel } from "@/lib/agents";

export function DirBadge({ dir, size = "sm" }: { dir: "LONG" | "SHORT"; size?: "sm" | "xs" }) {
  const px = size === "xs" ? "px-1 py-0.5 text-[8px]" : "px-1.5 py-0.5 text-[9px]";
  return dir === "LONG"
    ? <span className={`font-black rounded bg-green-100 text-green-700 border border-green-300 ${px}`}>▲ LONG</span>
    : <span className={`font-black rounded bg-red-100 text-red-700 border border-red-300 ${px}`}>▼ SHORT</span>;
}

// Dulu rantai ternary dgn "Accum." sebagai fallback — sehingga SETIAP lane yang
// bukan agent1/agent3 (termasuk BigMover) salah dilabeli "Accum.". Kini memakai
// registry: lane tak dikenal tampil apa adanya, bukan menyaru jadi lane lain.
const AGENT_BADGE_STYLE: Record<string, string> = {
  futures_agent1:         "bg-blue-100 text-blue-700 border-blue-200",
  futures_agent2:         "bg-purple-100 text-purple-700 border-purple-200",
  futures_agent3:         "bg-orange-100 text-orange-700 border-orange-200",
  futures_agent_bigmover: "bg-amber-100 text-amber-700 border-amber-200",
  opportunity_spot:       "bg-teal-100 text-teal-700 border-teal-200",
};

export function AgentBadge({ agent }: { agent: string }) {
  const cls = AGENT_BADGE_STYLE[agent] ?? "bg-neutral-100 text-neutral-600 border-neutral-200";
  return (
    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${cls}`}>
      {agentLabel(agent)}
    </span>
  );
}

export function AgentName({ agent }: { agent: string }): string {
  return agentLabel(agent);
}

export function TypeBadge({ type }: { type: "spot" | "futures" }) {
  return type === "spot"
    ? <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-teal-100 text-teal-700">SPOT</span>
    : <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">FUT</span>;
}

export function StatusDot({ ok, pulse }: { ok: boolean; pulse?: boolean }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${ok ? "bg-green-500" : "bg-red-500"} ${ok && pulse ? "animate-pulse" : ""}`} />
  );
}

export function RiskStatusBadge({ status }: { status: "SAFE" | "WARNING" | "DANGER" }) {
  const cfg = {
    SAFE:    "bg-green-100 text-green-700 border-green-200",
    WARNING: "bg-yellow-100 text-yellow-700 border-yellow-200",
    DANGER:  "bg-red-100 text-red-600 border-red-200 animate-pulse",
  };
  const emoji = { SAFE: "✅", WARNING: "⚠️", DANGER: "🚨" };
  return (
    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${cfg[status]}`}>
      {emoji[status]} {status}
    </span>
  );
}

export function PnlText({ value, className }: { value: number | null; className?: string }) {
  if (value == null) return <span className="text-neutral-400">—</span>;
  const color = value > 0 ? "text-green-600" : value < 0 ? "text-red-500" : "text-neutral-500";
  return (
    <span className={`font-black tabular-nums ${color} ${className ?? ""}`}>
      {value >= 0 ? "+" : ""}${Math.abs(value).toFixed(2)}
    </span>
  );
}

export function PctBadge({ pct }: { pct: number }) {
  const cls = pct > 0
    ? "bg-green-100 text-green-700"
    : pct < 0
    ? "bg-red-100 text-red-600"
    : "bg-neutral-100 text-neutral-500";
  return (
    <span className={`text-xs font-black tabular-nums px-1.5 py-0.5 rounded ${cls}`}>
      {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
    </span>
  );
}
