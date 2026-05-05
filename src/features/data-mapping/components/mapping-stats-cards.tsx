import { DataMappingStats } from "@/types/data-mapping";

interface MappingStatsCardsProps {
  stats: DataMappingStats;
}

export default function MappingStatsCards({ stats }: MappingStatsCardsProps) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="rounded-xl border border-gray-200 bg-white p-3">
        <div className="text-[11px] text-gray-500">Total mappings</div>
        <div className="mt-1 text-xl font-medium text-gray-900">{stats.total}</div>
      </div>

      <div className="rounded-xl border border-gray-200 border-l-[3px] border-l-primarygreen bg-white p-3">
        <div className="text-[11px] text-gray-500">Active</div>
        <div className="mt-1 text-xl font-medium text-primarygreen">{stats.active}</div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-3">
        <div className="text-[11px] text-gray-500">Fields mapped</div>
        <div className="mt-1 text-xl font-medium text-gray-900">{stats.fieldsMapped}</div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-3">
        <div className="text-[11px] text-gray-500">Open issues</div>
        <div className="mt-1 text-xl font-medium text-rose-600">{stats.issues}</div>
      </div>
    </div>
  );
}
