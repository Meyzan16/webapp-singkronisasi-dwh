// PLAN_v8 — SPOT lane mapping (single source of truth for badges/labels across
// dashboard + history). Maps alert_type / entry_mode → friendly lane + its
// auto-open threshold, so the UI can explain "kenapa score 65 open".

export interface LaneInfo {
  key: string;
  label: string;
  emoji: string;
  /** auto-open threshold for this lane (raw score) */
  autoScore: number;
  /** tailwind classes for a small badge */
  badge: string;
}

export const LANES: Record<string, LaneInfo> = {
  accumulation: { key: "accumulation", label: "Accumulation", emoji: "📦", autoScore: 85, badge: "bg-blue-100 text-blue-700" },
  breakout:     { key: "breakout",     label: "Breakout",     emoji: "💥", autoScore: 75, badge: "bg-orange-100 text-orange-700" },
  bigmover:     { key: "bigmover",     label: "Big Mover",    emoji: "🚀", autoScore: 65, badge: "bg-yellow-100 text-yellow-700" },
  early_radar:  { key: "early_radar",  label: "Early Radar",  emoji: "🛰", autoScore: 85, badge: "bg-rose-100 text-rose-700" },
  weekly:       { key: "weekly",       label: "Weekly",       emoji: "📅", autoScore: 85, badge: "bg-purple-100 text-purple-700" },
};

const FALLBACK: LaneInfo = { key: "other", label: "Opportunity", emoji: "🎯", autoScore: 85, badge: "bg-neutral-100 text-neutral-600" };

/**
 * Resolve the lane for a spot position from its alert_type (+ entry_mode fallback).
 * alert_type values seen in DB: squeeze, accumulation, breakout_pump,
 * bigmover_chase, early_radar. entry_mode: fresh_setup, bigmover_chase, momentum_chase.
 */
export function laneForSpot(alertType?: string | null, entryMode?: string | null): LaneInfo {
  const a = (alertType ?? "").toLowerCase();
  const e = (entryMode ?? "").toLowerCase();
  if (a.includes("bigmover") || e.includes("bigmover")) return LANES.bigmover;
  if (a.includes("early") || e.includes("early"))       return LANES.early_radar;
  if (a.includes("breakout"))                            return LANES.breakout;
  if (a.includes("weekly"))                              return LANES.weekly;
  // squeeze / accumulation / fresh_setup / momentum_chase → accumulation lane
  if (a.includes("squeeze") || a.includes("accumulation") || e.includes("fresh") || e.includes("momentum"))
    return LANES.accumulation;
  return FALLBACK;
}

/**
 * Human open-reason for a spot position:
 * - manual (force-open) → "🖐 Manual"
 * - auto → "{emoji} {Lane} · auto ≥{threshold}"
 */
export function openReason(alertType?: string | null, entryMode?: string | null, manual?: boolean): string {
  if (manual) return "🖐 Force-Open (manual)";
  const l = laneForSpot(alertType, entryMode);
  return `${l.emoji} ${l.label} · auto ≥${l.autoScore}`;
}
