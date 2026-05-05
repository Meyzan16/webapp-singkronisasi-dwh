import { DataMappingRule, MappingStatus } from "@/types/data-mapping";
import { Edit3, Eye, GitCompareArrows } from "lucide-react";

interface MappingTableProps {
  mappings: DataMappingRule[];
}

const statusStyles: Record<MappingStatus, string> = {
  Active: "bg-emerald-100 text-emerald-800",
  Draft: "bg-gray-100 text-gray-700",
  Issue: "bg-rose-100 text-rose-800",
};

export default function MappingTable({ mappings }: MappingTableProps) {
  if (mappings.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
        No mappings found matching your filters.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
      <table className="w-full text-left text-xs">
        <thead className="border-b border-gray-200 bg-gray-50 text-[10px] uppercase tracking-wide text-gray-600">
          <tr>
            <th className="px-3 py-2.5 font-medium">Mapping ID</th>
            <th className="px-3 py-2.5 font-medium">Mapping name</th>
            <th className="px-3 py-2.5 font-medium">Source</th>
            <th className="px-3 py-2.5 font-medium">Target</th>
            <th className="px-3 py-2.5 font-medium">Fields</th>
            <th className="px-3 py-2.5 font-medium">Status</th>
            <th className="px-3 py-2.5 font-medium">Validation</th>
            <th className="px-3 py-2.5 font-medium">Updated</th>
            <th className="px-3 py-2.5 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 text-xs">
          {mappings.map((mapping) => (
            <tr key={mapping.id} className="transition-colors hover:bg-gray-50">
              <td className="px-3 py-2.5 font-medium text-gray-900">{mapping.id}</td>
              <td className="px-3 py-2.5">
                <div className="font-medium text-gray-900">{mapping.name}</div>
                <div className="mt-0.5 text-[11px] text-gray-400">{mapping.owner}</div>
              </td>
              <td className="px-3 py-2.5 text-gray-600">
                <div>{mapping.sourceSystem}</div>
                <div className="mt-0.5 text-[11px] text-gray-400">{mapping.sourceObject}</div>
              </td>
              <td className="px-3 py-2.5 text-gray-600">
                <div>{mapping.targetSystem}</div>
                <div className="mt-0.5 text-[11px] text-gray-400">{mapping.targetObject}</div>
              </td>
              <td className="px-3 py-2.5 text-gray-600">{mapping.fields}</td>
              <td className="px-3 py-2.5">
                <span className={`rounded-md px-2.5 py-0.5 text-xs font-semibold ${statusStyles[mapping.status]}`}>
                  {mapping.status}
                </span>
              </td>
              <td className="px-3 py-2.5">
                <div className="flex min-w-[92px] items-center gap-2">
                  <div className="h-1.5 flex-1 rounded-full bg-gray-100">
                    <div
                      className={`h-1.5 rounded-full ${
                        mapping.validationScore >= 90
                          ? "bg-primarygreen"
                          : mapping.validationScore >= 80
                            ? "bg-amber-500"
                            : "bg-rose-500"
                      }`}
                      style={{ width: `${mapping.validationScore}%` }}
                    />
                  </div>
                  <span className="text-[11px] text-gray-500">{mapping.validationScore}%</span>
                </div>
              </td>
              <td className="px-3 py-2.5 text-gray-600">{mapping.lastUpdated}</td>
              <td className="px-3 py-2.5">
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gray-100 text-gray-700 transition hover:bg-gray-200"
                    title="View mapping"
                  >
                    <Eye size={14} />
                  </button>
                  <button
                    type="button"
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gray-100 text-gray-700 transition hover:bg-gray-200"
                    title="Compare schema"
                  >
                    <GitCompareArrows size={14} />
                  </button>
                  <button
                    type="button"
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-emerald-100 text-primarygreen transition hover:bg-emerald-200"
                    title="Edit mapping"
                  >
                    <Edit3 size={14} />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
