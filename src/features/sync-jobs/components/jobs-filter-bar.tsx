// src/features/sync-jobs/components/jobs-filter-bar.tsx

"use client";

import { JobStatusFilter } from "@/types/sync-jobs-extended";
import { FiSearch } from "react-icons/fi";

interface JobsFilterBarProps {
  activeStatus: JobStatusFilter;
  onStatusChange: (status: JobStatusFilter) => void;
  search: string;
  onSearchChange: (value: string) => void;
  onReset: () => void;
}

const statusOptions: JobStatusFilter[] = ["All", "Running", "Success", "Failed"];

export default function JobsFilterBar({
  activeStatus,
  onStatusChange,
  search,
  onSearchChange,
  onReset,
}: JobsFilterBarProps) {
  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-3">
      {/* Top row: Date picker + Search + Reset */}
      <div className="flex flex-wrap items-center gap-2">
        <button className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50">
          📅 Select Date Range
        </button>
        <div className="flex-1" /> {/* Spacer */}
        <div className="relative">
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search jobs..."
            className="h-8 w-full min-w-[200px] rounded-lg border border-gray-200 bg-white py-1.5 pl-3 pr-8 text-xs text-gray-700 placeholder:text-gray-400 focus:border-primarygreen focus:outline-none focus:ring-1 focus:ring-primarygreen"
          />
          <FiSearch
            size={14}
            className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400"
          />
        </div>
        <button
          onClick={onReset}
          className="rounded-lg bg-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-300"
        >
          Reset
        </button>
      </div>

      {/* Bottom row: Status pills */}
      <div className="flex flex-wrap items-center gap-1.5 border-t border-gray-100 pt-3">
        {statusOptions.map((status) => {
          const isActive = activeStatus === status;
          return (
            <button
              key={status}
              onClick={() => onStatusChange(status)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                isActive
                  ? "bg-primarygreen text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              {status}
            </button>
          );
        })}
      </div>
    </div>
  );
}