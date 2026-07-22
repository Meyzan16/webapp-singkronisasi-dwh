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
};

/**
 * Lane SPOT yang benar-benar di-scan agent (agents/opportunity/scanner.py:
 * accumulation, breakout, bigmover, early_radar). Dipakai untuk panel performa
 * supaya lane yang aktif tapi NOL trade tetap terlihat — bukan hilang diam-diam.
 * `weekly` sengaja tidak masuk: tak ada alert_type spot yang menghasilkannya.
 */
export const SPOT_LANE_KEYS = ["bigmover", "accumulation", "breakout", "early_radar"] as const;

const FALLBACK: LaneInfo ={ key: "other", label: "Opportunity", emoji: "🎯", autoScore: 85, badge: "bg-neutral-100 text-neutral-600" };

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
  // squeeze / accumulation / fresh_setup / momentum_chase → accumulation lane
  if (a.includes("squeeze") || a.includes("accumulation") || e.includes("fresh") || e.includes("momentum"))
    return LANES.accumulation;
  return FALLBACK;
}

/**
 * PLAN_SPOT_LANES S6 — lane sebuah posisi, memakai field `lane` immutable dari
 * backend bila ada. `laneForSpot` (di atas) hanya cadangan untuk respons lama:
 * ia ikut membaca `entry_mode`, yang DIMUTASI monitor jadi "momentum_chase"
 * begitu TP2/TP3 tersentuh — jadi ia tidak layak jadi kunci analitik.
 */
export function laneFromPosition(p: {
  lane?: string | null;
  alert_type?: string | null;
  entry_mode?: string | null;
}): LaneInfo {
  const key = (p.lane ?? "").trim().toLowerCase();
  if (key && LANES[key]) return LANES[key];
  return laneForSpot(p.alert_type, p.entry_mode);
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
