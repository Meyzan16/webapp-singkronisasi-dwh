// src/app/(content)/dashboards/page.tsx

"use client";

import { FiRefreshCw, FiPauseCircle } from "react-icons/fi";
import { Button } from "@/components/ui/button";

import StatsOverview from "@/features/dashboard/components/stats-overview";
import OpsMetrics from "@/features/dashboard/components/ops-metrics";
import ActivityChart from "@/features/dashboard/components/activity-chart";
import ErrorBreakdown from "@/features/dashboard/components/error-breakdown";
import DataSourcesList from "@/features/dashboard/components/data-sources-list";
import UpcomingJobs from "@/features/dashboard/components/upcoming-jobs";
import RecentJobsTable from "@/features/dashboard/components/recent-jobs-table";
import NotificationsPanel from "@/features/dashboard/components/notifications-panel";

import {
  dashboardStats,
  opsMetrics,
  weeklyActivity,
  errorBuckets,
  dataSources,
  upcomingJobs,
  recentJobs,
  notifications,
} from "@/features/dashboard/data/mock-data";

export default function DashboardPage() {
  // TODO: ganti mock data dengan fetch dari API saat backend siap

  const handleRefresh = () => {
    // TODO: panggil API refresh data
    console.log("Refresh dashboard");
  };

  const handlePauseAll = () => {
    // TODO: panggil API pause semua running jobs
    console.log("Pause all jobs");
  };

  return (
    <main className="pb-8">
      {/* Header actions — title sudah dihandle Navbar via pathnameMap */}
      <div className="mb-4 flex items-center justify-end gap-2">
        <Button variant="outline" size="sm" className="rounded-md">
          Today ▾
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handlePauseAll}
          className="rounded-md"
        >
          <FiPauseCircle size={14} />
          Pause all
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={handleRefresh}
          className="rounded-md"
        >
          <FiRefreshCw size={14} />
          Refresh
        </Button>
      </div>

      {/* Section 1 — KPI utama */}
      <div className="mb-3">
        <StatsOverview stats={dashboardStats} />
      </div>

      {/* Section 2 — Metrik operasional */}
      <div className="mb-4">
        <OpsMetrics metrics={opsMetrics} />
      </div>

      {/* Section 3 — Activity chart + Error breakdown (1.6:1) */}
      <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-[1.6fr_1fr]">
        <ActivityChart data={weeklyActivity} />
        <ErrorBreakdown buckets={errorBuckets} />
      </div>

      {/* Section 4 — Data sources + Upcoming jobs (1:1) */}
      <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
        <DataSourcesList sources={dataSources} />
        <UpcomingJobs jobs={upcomingJobs} />
      </div>

      {/* Section 5 — Recent jobs + Notifications (1.6:1) */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1.6fr_1fr]">
        <RecentJobsTable jobs={recentJobs ?? []} />
        <NotificationsPanel notifications={notifications} />
      </div>
    </main>
  );
}