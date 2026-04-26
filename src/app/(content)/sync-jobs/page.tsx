// src/app/(content)/sync-jobs/page.tsx

"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { JobStatusFilter, SyncJobDetail } from "@/types/sync-jobs-extended";

import JobStatsCards from "@/features/sync-jobs/components/job-stats-cards";
import JobsFilterBar from "@/features/sync-jobs/components/jobs-filter-bar";
import JobsTableEnhanced from "@/features/sync-jobs/components/jobs-table-enhanced";
import JobDetailDrawer from "@/features/sync-jobs/components/job-detail-drawer";
import Pagination from "@/features/sync-jobs/components/pagination";

import { syncJobsStats, syncJobsData } from "@/features/sync-jobs/data/mock-data";

const ITEMS_PER_PAGE = 10;

export default function SyncJobsPage() {
  // Filter state
  const [statusFilter, setStatusFilter] = useState<JobStatusFilter>("All");
  const [searchQuery, setSearchQuery] = useState("");

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);

  // Drawer state
  const [selectedJob, setSelectedJob] = useState<SyncJobDetail | null>(null);

  // Filtered & paginated data
  const filteredJobs = useMemo(() => {
    return syncJobsData.filter((job) => {
      // Status filter
      const statusMatch = statusFilter === "All" || job.status === statusFilter;

      // Search filter
      const searchLower = searchQuery.toLowerCase();
      const searchMatch =
        job.id.toLowerCase().includes(searchLower) ||
        job.name.toLowerCase().includes(searchLower);

      return statusMatch && searchMatch;
    });
  }, [statusFilter, searchQuery]);

  const totalPages = Math.ceil(filteredJobs.length / ITEMS_PER_PAGE);
  const paginatedJobs = useMemo(() => {
    const start = (currentPage - 1) * ITEMS_PER_PAGE;
    return filteredJobs.slice(start, start + ITEMS_PER_PAGE);
  }, [filteredJobs, currentPage]);

  // Handlers
  const handleReset = () => {
    setStatusFilter("All");
    setSearchQuery("");
    setCurrentPage(1);
  };

  const handleViewDetails = (job: SyncJobDetail) => {
    setSelectedJob(job);
  };

  const handleCreateJob = () => {
    // TODO: buka modal create job
    console.log("Create new job");
  };

  return (
    <main className="space-y-4 pb-8">
      {/* Header actions */}
      <div className="flex items-center justify-end">
        <Button
          variant="primary"
          size="md"
          onClick={handleCreateJob}
          className="rounded-xl"
        >
          + Create Job
        </Button>
      </div>

      {/* Stat cards */}
      <JobStatsCards stats={syncJobsStats} />

      {/* Filter bar */}
      <JobsFilterBar
        activeStatus={statusFilter}
        onStatusChange={setStatusFilter}
        search={searchQuery}
        onSearchChange={setSearchQuery}
        onReset={handleReset}
      />

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <JobsTableEnhanced jobs={paginatedJobs} onViewDetails={handleViewDetails} />
        {filteredJobs.length > ITEMS_PER_PAGE && (
          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            totalItems={filteredJobs.length}
            itemsPerPage={ITEMS_PER_PAGE}
            onPageChange={setCurrentPage}
          />
        )}
      </div>

      {/* Drawer detail */}
      <JobDetailDrawer job={selectedJob} onClose={() => setSelectedJob(null)} />
    </main>
  );
}