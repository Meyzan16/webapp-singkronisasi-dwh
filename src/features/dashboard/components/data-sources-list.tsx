// src/features/dashboard/components/data-sources-list.tsx

import { DataSource, DataSourceStatus } from "@/types/dashboard";

interface DataSourcesListProps {
  sources: DataSource[];
}

const statusStyles: Record<DataSourceStatus, string> = {
  Online: "bg-emerald-50 text-emerald-700",
  Slow: "bg-amber-50 text-amber-700",
  Offline: "bg-rose-50 text-rose-700",
};

export default function DataSourcesList({ sources }: DataSourcesListProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-3 text-sm font-medium text-gray-900">Data sources</div>

      <div className="flex flex-col">
        {sources.map((src, idx) => (
          <div
            key={src.id}
            className={`flex items-center justify-between py-2 ${
              idx < sources.length - 1 ? "border-b border-gray-100" : ""
            }`}
          >
            <div>
              <div className="text-[13px] text-gray-900">{src.name}</div>
              <div className="text-[11px] text-gray-400">{src.lastPing}</div>
            </div>
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] ${statusStyles[src.status]}`}
            >
              ● {src.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}