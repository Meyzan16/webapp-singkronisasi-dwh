"use client";

type Color = "green" | "blue" | "teal";

const COLOR_MAP: Record<Color, { dot: string; bg: string; text: string; border: string }> = {
  green: { dot: "bg-green-500",  bg: "bg-green-50",  text: "text-green-700", border: "border-green-200" },
  blue:  { dot: "bg-blue-500",   bg: "bg-blue-50",   text: "text-blue-700",  border: "border-blue-200"  },
  teal:  { dot: "bg-teal-500",   bg: "bg-teal-50",   text: "text-teal-700",  border: "border-teal-200"  },
};

export function LiveBadge({ countdown, color = "green" }: { countdown: number; color?: Color }) {
  const c = COLOR_MAP[color];
  return (
    <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border ${c.bg} ${c.border}`}>
      <span className={`w-2 h-2 rounded-full animate-pulse ${c.dot}`} />
      <span className={`text-xs font-bold ${c.text}`}>LIVE</span>
      <span className={`text-xs tabular-nums ${c.text}`}>{countdown}s</span>
    </div>
  );
}

export type ConnState = "connecting" | "connected" | "reconnecting" | "paused";

export const CONN_META: Record<ConnState, { dot: string; label: string; color: string }> = {
  connected:    { dot: "bg-green-400",                label: "LIVE",        color: "text-green-400 border-green-500/40 bg-green-500/10"   },
  connecting:   { dot: "bg-yellow-400 animate-pulse", label: "CONNECTING",  color: "text-yellow-400 border-yellow-500/40 bg-yellow-500/10" },
  reconnecting: { dot: "bg-orange-400 animate-pulse", label: "RECONN...",   color: "text-orange-400 border-orange-500/40 bg-orange-500/10" },
  paused:       { dot: "bg-neutral-500",              label: "PAUSED",      color: "text-neutral-400 border-neutral-600 bg-neutral-700/50" },
};

export function ConnBadge({ state }: { state: ConnState }) {
  const m = CONN_META[state];
  return (
    <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-bold ${m.color}`}>
      <span className={`w-2 h-2 rounded-full ${m.dot}`} />
      {m.label}
    </div>
  );
}
