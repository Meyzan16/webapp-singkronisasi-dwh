// src/features/dashboard/components/upcoming-jobs.tsx

import { UpcomingJob } from "@/types/dashboard";

interface UpcomingJobsProps {
  jobs: UpcomingJob[];
}

// Job yang akan jalan dalam 15 menit dianggap "imminent" (highlight hijau)
const IMMINENT_THRESHOLD_MIN = 15;

export default function UpcomingJobs({ jobs }: UpcomingJobsProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-medium text-gray-900">Upcoming jobs</div>
        <div className="text-[11px] text-gray-500">Next 1 hour</div>
      </div>

      <div className="flex flex-col">
        {jobs.map((job, idx) => {
          const imminent = job.inMinutes <= IMMINENT_THRESHOLD_MIN;

          return (
            <div
              key={job.id}
              className={`flex items-center gap-3 py-2 ${
                idx < jobs.length - 1 ? "border-b border-gray-100" : ""
              }`}
            >
              {/* Countdown badge */}
              <div
                className={`w-9 shrink-0 rounded-md py-1 text-center text-[11px] font-medium ${
                  imminent
                    ? "bg-emerald-50 text-primarygreen"
                    : "bg-gray-100 text-gray-500"
                }`}
              >
                {job.inMinutes}m
              </div>

              {/* Detail */}
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] text-gray-900">{job.name}</div>
                <div className="text-[11px] text-gray-400">
                  {job.schedule} · {job.source} → {job.target}
                </div>
              </div>

              {/* Scheduled time */}
              <span className="text-[11px] text-gray-500">{job.scheduledAt}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}