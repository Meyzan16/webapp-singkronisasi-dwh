// src/features/dashboard/components/recent-jobs-table.tsx

"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";

// Inline type untuk menghindari konflik import
interface RecentJob {
  id: string;
  name: string;
  status: "Running" | "Success" | "Failed";
  lastRun: string;
  records: number;
}

interface RecentJobsTableProps {
  jobs: RecentJob[];
}

export default function RecentJobsTable({ jobs }: RecentJobsTableProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-medium text-gray-900">Recent sync jobs</div>
        <Link
          href="/sync-jobs"
          className="text-[11px] text-primarygreen hover:underline"
        >
          View all →
        </Link>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-gray-500">
              <th className="border-b border-gray-100 px-1 py-1.5 font-normal">Job</th>
              <th className="border-b border-gray-100 px-1 py-1.5 font-normal">Status</th>
              <th className="border-b border-gray-100 px-1 py-1.5 font-normal">Records</th>
              <th className="border-b border-gray-100 px-1 py-1.5 font-normal">Last run</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job, idx) => (
              <tr key={job.id}>
                <td
                  className={`px-1 py-2 text-gray-900 ${
                    idx < jobs.length - 1 ? "border-b border-gray-100" : ""
                  }`}
                >
                  {job.name}
                </td>
                <td
                  className={`px-1 py-2 ${
                    idx < jobs.length - 1 ? "border-b border-gray-100" : ""
                  }`}
                >
                  <Badge
                    variant={job.status.toLowerCase() as "running" | "success" | "failed"}
                  >
                    {job.status}
                  </Badge>
                </td>
                <td
                  className={`px-1 py-2 text-gray-500 ${
                    idx < jobs.length - 1 ? "border-b border-gray-100" : ""
                  }`}
                >
                  {job.records.toLocaleString()}
                </td>
                <td
                  className={`px-1 py-2 text-gray-500 ${
                    idx < jobs.length - 1 ? "border-b border-gray-100" : ""
                  }`}
                >
                  {job.lastRun}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}