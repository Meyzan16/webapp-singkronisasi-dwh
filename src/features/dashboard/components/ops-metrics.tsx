// src/features/dashboard/components/ops-metrics.tsx

import { OpsMetrics as OpsMetricsType } from "@/types/dashboard";

interface OpsMetricsProps {
  metrics: OpsMetricsType;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export default function OpsMetrics({ metrics }: OpsMetricsProps) {
  const withinSla = metrics.avgSyncLagSeconds < metrics.syncLagSlaSeconds;
  const slaTargetMin = Math.floor(metrics.syncLagSlaSeconds / 60);

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {/* Avg Sync Lag */}
      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="text-xs text-gray-500">Avg Sync Lag</div>
        <div className="mt-1.5 flex items-baseline gap-2">
          <span className="text-2xl font-medium text-gray-900">
            {formatDuration(metrics.avgSyncLagSeconds)}
          </span>
          <span
            className={`text-[11px] ${
              withinSla ? "text-primarygreen" : "text-rose-600"
            }`}
          >
            {withinSla ? "within SLA" : "exceeds SLA"}
          </span>
        </div>
        <div className="mt-1 text-[11px] text-gray-400">
          Target: &lt; {slaTargetMin} min
        </div>
      </div>

      {/* Data Freshness */}
      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="text-xs text-gray-500">Data Freshness</div>
        <div className="mt-1.5 text-2xl font-medium text-gray-900">
          {metrics.dataFreshness}
        </div>
        <div className="mt-1 text-[11px] text-gray-400">Last successful update</div>
      </div>

      {/* Queue Backlog */}
      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="text-xs text-gray-500">Queue Backlog</div>
        <div className="mt-1.5 flex items-baseline gap-2">
          <span className="text-2xl font-medium text-gray-900">
            {metrics.queueBacklog}
          </span>
          <span className="text-[11px] text-gray-500">jobs waiting</span>
        </div>
        <div className="mt-1 text-[11px] text-gray-400">
          Est. clear in {metrics.queueClearEstimateMinutes} min
        </div>
      </div>
    </div>
  );
}