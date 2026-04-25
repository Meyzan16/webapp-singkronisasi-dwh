"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SyncJob } from "@/types/sync-jobs";

interface SyncJobsTableProps {
  jobs: SyncJob[];
}

export default function SyncJobsTable({ jobs }: SyncJobsTableProps) {
  if (jobs.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
        No jobs found.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className="border-b px-3 py-3 text-xs font-medium uppercase tracking-wide text-gray-600">Job ID</th>
            <th className="border-b px-3 py-3 text-xs font-medium uppercase tracking-wide text-gray-600">Job Name</th>
            <th className="border-b px-3 py-3 text-xs font-medium uppercase tracking-wide text-gray-600">Status</th>
            <th className="border-b px-3 py-3 text-xs font-medium uppercase tracking-wide text-gray-600">Last Run</th>
            <th className="border-b px-3 py-3 text-xs font-medium uppercase tracking-wide text-gray-600">Duration</th>
            <th className="border-b px-3 py-3 text-xs font-medium uppercase tracking-wide text-gray-600">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {jobs.map((job) => (
            <tr key={`${job.id}-${job.name}`} className="hover:bg-gray-50">
              <td className="px-3 py-3 font-medium text-gray-700">{job.id}</td>
              <td className="px-3 py-3 text-gray-700">{job.name}</td>
              <td className="px-3 py-3">
                <Badge variant={job.status.toLowerCase() as "running" | "success" | "failed"}>{job.status}</Badge>
              </td>
              <td className="px-3 py-3 text-gray-700">{job.lastRun}</td>
              <td className="px-3 py-3 text-gray-700">{job.duration}</td>
              <td className="px-3 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="secondary">View</Button>
                  {job.status === "Failed" ? (
                    <Button size="sm" variant="primary">Retry</Button>
                  ) : job.status === "Running" ? (
                    <Button size="sm" variant="muted">Stop</Button>
                  ) : (
                    <Button size="sm" variant="outline">Re-run</Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}