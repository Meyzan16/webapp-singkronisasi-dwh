// src/features/dashboard/components/stats-overview.tsx

import StatCard from "./stat-card";
import { DashboardStats } from "@/types/dashboard";

interface StatsOverviewProps {
  stats: DashboardStats;
}

// Format angka besar: 2.34M, 12.5K, dst.
function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default function StatsOverview({ stats }: StatsOverviewProps) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard
        label="Total Jobs"
        value={stats.totalJobs}
        hint={`↑ ${stats.totalJobsDelta} from yesterday`}
        hintTone="muted"
      />

      <StatCard
        label="Running"
        value={stats.running}
        valueTone="success"
        accent
        liveDot
        hint="Live now"
      />

      <StatCard
        label="Records Synced Today"
        value={formatCompact(stats.recordsSyncedToday)}
        hint={`~${stats.avgRecordsPerSec.toLocaleString()} rec/sec avg`}
        hintTone="muted"
      />

      <StatCard
        label="Failed Today"
        value={stats.failedToday}
        valueTone="danger"
        hint="Needs attention"
        hintTone="danger"
      />
    </div>
  );
}