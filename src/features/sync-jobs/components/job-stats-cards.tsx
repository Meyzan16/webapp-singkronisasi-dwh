// src/features/sync-jobs/components/job-stats-cards.tsx

import { SyncJobsStats } from "@/types/sync-jobs-extended";

interface JobStatsCardsProps {
  stats: SyncJobsStats;
}

export default function JobStatsCards({ stats }: JobStatsCardsProps) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="rounded-xl border border-gray-200 bg-white p-3">
        <div className="text-[11px] text-gray-500">Total</div>
        <div className="mt-1 text-xl font-medium text-gray-900">{stats.total}</div>
      </div>

      <div className="rounded-xl border border-gray-200 border-l-[3px] border-l-primarygreen bg-white p-3">
        <div className="text-[11px] text-gray-500">Running</div>
        <div className="mt-1 text-xl font-medium text-primarygreen">{stats.running}</div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-3">
        <div className="text-[11px] text-gray-500">Success today</div>
        <div className="mt-1 text-xl font-medium text-emerald-700">{stats.successToday}</div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-3">
        <div className="text-[11px] text-gray-500">Failed today</div>
        <div className="mt-1 text-xl font-medium text-rose-600">{stats.failedToday}</div>
      </div>
    </div>
  );
}