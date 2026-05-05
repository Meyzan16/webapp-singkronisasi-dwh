"use client";

import { MappingStatusFilter } from "@/types/data-mapping";
import { Search } from "lucide-react";

interface MappingFilterBarProps {
  activeStatus: MappingStatusFilter;
  onStatusChange: (status: MappingStatusFilter) => void;
  source: string;
  onSourceChange: (source: string) => void;
  sourceOptions: string[];
  search: string;
  onSearchChange: (value: string) => void;
  onReset: () => void;
}

const statusOptions: MappingStatusFilter[] = ["All", "Active", "Draft", "Issue"];

export default function MappingFilterBar({
  activeStatus,
  onStatusChange,
  source,
  onSourceChange,
  sourceOptions,
  search,
  onSearchChange,
  onReset,
}: MappingFilterBarProps) {
  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={source}
          onChange={(event) => onSourceChange(event.target.value)}
          className="h-8 rounded-lg border border-gray-200 bg-white px-3 text-xs text-gray-700 focus:border-primarygreen focus:outline-none focus:ring-1 focus:ring-primarygreen"
        >
          <option value="All">All sources</option>
          {sourceOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>

        <div className="flex-1" />

        <div className="relative">
          <input
            type="text"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search mappings..."
            className="h-8 w-full min-w-[220px] rounded-lg border border-gray-200 bg-white py-1.5 pl-3 pr-8 text-xs text-gray-700 placeholder:text-gray-400 focus:border-primarygreen focus:outline-none focus:ring-1 focus:ring-primarygreen"
          />
          <Search
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
