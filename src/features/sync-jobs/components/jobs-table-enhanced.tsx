// src/features/sync-jobs/components/jobs-table-enhanced.tsx

"use client";

import { useState } from "react";
import { SyncJobDetail } from "@/types/sync-jobs-extended";
import { Badge } from "@/components/ui/badge";
import { FiEye, FiFileText, FiPauseCircle, FiRefreshCw, FiPlayCircle } from "react-icons/fi";

interface JobsTableEnhancedProps {
  jobs: SyncJobDetail[];
  onViewDetails: (job: SyncJobDetail) => void;
}

export default function JobsTableEnhanced({ jobs, onViewDetails }: JobsTableEnhancedProps) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const allSelected = jobs.length > 0 && selectedIds.size === jobs.length;
  const someSelected = selectedIds.size > 0 && !allSelected;

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(jobs.map((j) => j.id)));
    }
  };

  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedIds(next);
  };

  if (jobs.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
        No jobs found matching your filters.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
      <table className="w-full text-left text-xs">
        <thead className="border-b border-gray-200 bg-gray-50 text-[10px] uppercase tracking-wide text-gray-600">
          <tr>
            <th className="px-3 py-2.5">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = someSelected;
                }}
                onChange={toggleSelectAll}
                className="h-4 w-4 rounded border-gray-300 accent-primarygreen"
              />
            </th>
            <th className="px-3 py-2.5 font-medium">Job ID</th>
            <th className="px-3 py-2.5 font-medium">Job Name</th>
            <th className="px-3 py-2.5 font-medium">Status</th>
            <th className="px-3 py-2.5 font-medium">Last Run</th>
            <th className="px-3 py-2.5 font-medium">Duration</th>
            <th className="px-3 py-2.5 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 text-xs">
          {jobs.map((job) => {
            const isSelected = selectedIds.has(job.id);
            const isRunning = job.status === "Running";
            const isFailed = job.status === "Failed";

            return (
              <tr
                key={job.id}
                className={`transition-colors hover:bg-gray-50 ${
                  isSelected ? "bg-emerald-50/40" : ""
                }`}
              >
                <td className="px-3 py-2.5">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleSelect(job.id)}
                    className="h-4 w-4 rounded border-gray-300 accent-primarygreen"
                  />
                </td>
                <td className="px-3 py-2.5 font-medium text-gray-900">{job.id}</td>
                <td className="px-3 py-2.5 text-gray-900">{job.name}</td>
                <td className="px-3 py-2.5">
                  <Badge variant={job.status.toLowerCase() as "running" | "success" | "failed"}>
                    {job.status}
                  </Badge>
                </td>
                <td className="px-3 py-2.5 text-gray-600">{job.lastRun}</td>
                <td className="px-3 py-2.5 text-gray-600">{job.duration}</td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-1">
                    {/* View detail */}
                    <button
                      onClick={() => onViewDetails(job)}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gray-100 text-gray-700 transition hover:bg-gray-200"
                      title="View details"
                    >
                      <FiEye size={14} />
                    </button>

                    {/* Logs */}
                    <button
                      onClick={() => console.log("View logs", job.id)}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gray-100 text-gray-700 transition hover:bg-gray-200"
                      title="View logs"
                    >
                      <FiFileText size={14} />
                    </button>

                    {/* Action button (conditional) */}
                    {isRunning && (
                      <button
                        onClick={() => console.log("Pause", job.id)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-rose-100 text-rose-700 transition hover:bg-rose-200"
                        title="Pause job"
                      >
                        <FiPauseCircle size={14} />
                      </button>
                    )}
                    {isFailed && (
                      <button
                        onClick={() => console.log("Retry", job.id)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-emerald-100 text-primarygreen transition hover:bg-emerald-200"
                        title="Retry job"
                      >
                        <FiRefreshCw size={14} />
                      </button>
                    )}
                    {!isRunning && !isFailed && (
                      <button
                        onClick={() => console.log("Re-run", job.id)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-blue-100 text-blue-700 transition hover:bg-blue-200"
                        title="Re-run job"
                      >
                        <FiPlayCircle size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}