// src/features/sync-jobs/components/job-detail-drawer.tsx

"use client";

import { SyncJobDetail } from "@/types/sync-jobs-extended";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FiX } from "react-icons/fi";

interface JobDetailDrawerProps {
  job: SyncJobDetail | null;
  onClose: () => void;
}

export default function JobDetailDrawer({ job, onClose }: JobDetailDrawerProps) {
  if (!job) return null;

  const isRunning = job.status === "Running";
  const isFailed = job.status === "Failed";

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 z-40 bg-black/20"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <aside className="fixed right-0 top-0 z-50 h-screen w-full max-w-md overflow-y-auto border-l border-gray-200 bg-white shadow-xl">
        <div className="flex h-full flex-col">
          {/* Header */}
          <div className="border-b border-gray-100 p-4">
            <div className="mb-3 flex items-start justify-between">
              <div className="flex-1">
                <div className="font-mono text-[11px] text-gray-500">
                  JOB · {job.id}
                </div>
                <h2 className="mt-1 text-base font-semibold text-gray-900">
                  {job.name}
                </h2>
                <div className="mt-2">
                  <Badge
                    variant={job.status.toLowerCase() as "running" | "success" | "failed"}
                  >
                    {job.status}
                  </Badge>
                </div>
              </div>
              <button
                onClick={onClose}
                className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                aria-label="Close drawer"
              >
                <FiX size={18} />
              </button>
            </div>

            {/* Progress (hanya tampil kalau status Running dan ada progress) */}
            {isRunning && job.progress && (
              <div className="mt-3 rounded-lg bg-gray-50 p-3">
                <div className="mb-1.5 text-[11px] text-gray-500">
                  Progress · {job.progress.current.toLocaleString()} /{" "}
                  ~{job.progress.total.toLocaleString()} records
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-gray-200">
                  <div
                    className="h-full bg-primarygreen transition-all"
                    style={{ width: `${job.progress.percentage}%` }}
                  />
                </div>
                <div className="mt-1.5 flex justify-between text-[10px] text-gray-500">
                  <span>{job.progress.percentage}%</span>
                  <span>~{job.progress.estimatedMinutesRemaining} min remaining</span>
                </div>
              </div>
            )}
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto p-4">
            {/* Configuration */}
            <section className="mb-6">
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-gray-500">
                Configuration
              </h3>
              <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 text-xs">
                <dt className="text-gray-500">Source</dt>
                <dd className="font-medium text-gray-900">
                  {job.config.source}
                  {job.config.sourceTable && (
                    <span className="ml-1 font-mono text-[11px] text-gray-600">
                      .{job.config.sourceTable}
                    </span>
                  )}
                </dd>

                <dt className="text-gray-500">Target</dt>
                <dd className="font-medium text-gray-900">
                  {job.config.target}
                  {job.config.targetTable && (
                    <span className="ml-1 font-mono text-[11px] text-gray-600">
                      .{job.config.targetTable}
                    </span>
                  )}
                </dd>

                <dt className="text-gray-500">Schedule</dt>
                <dd className="font-medium text-gray-900">{job.config.schedule}</dd>

                <dt className="text-gray-500">Owner</dt>
                <dd className="text-gray-900">{job.config.owner}</dd>
              </dl>
            </section>

            {/* Recent runs */}
            <section>
              <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-gray-500">
                Recent runs
              </h3>
              <div className="space-y-0 text-[11px]">
                {job.recentRuns.map((run, idx) => {
                  const runStatusColor =
                    run.status === "Running"
                      ? "text-blue-600"
                      : run.status === "Success"
                      ? "text-emerald-700"
                      : "text-rose-600";

                  return (
                    <div
                      key={run.id}
                      className={`flex items-center justify-between py-1.5 ${
                        idx < job.recentRuns.length - 1 ? "border-b border-gray-100" : ""
                      }`}
                    >
                      <span className="text-gray-900">{run.timestamp}</span>
                      <span className={runStatusColor}>
                        {run.status}
                        {run.duration && ` · ${run.duration}`}
                      </span>
                    </div>
                  );
                })}
              </div>
            </section>
          </div>

          {/* Footer actions */}
          <div className="border-t border-gray-100 p-4">
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="md"
                className="flex-1"
                onClick={() => console.log("View logs for", job.id)}
              >
                View logs
              </Button>
              {isRunning && (
                <Button
                  variant="destructive"
                  size="md"
                  className="flex-1"
                  onClick={() => console.log("Pause job", job.id)}
                >
                  ⏸ Pause
                </Button>
              )}
              {isFailed && (
                <Button
                  variant="primary"
                  size="md"
                  className="flex-1"
                  onClick={() => console.log("Retry job", job.id)}
                >
                  ↻ Retry
                </Button>
              )}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}