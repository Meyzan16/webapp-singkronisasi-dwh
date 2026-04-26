// src/types/sync-jobs-extended.ts

import { SyncJob, SyncJobStatus } from "./sync-jobs";

// ─── Extended SyncJob dengan config detail untuk drawer ───────────────────────

export interface SyncJobDetail extends SyncJob {
  // Progress (untuk Running jobs)
  progress?: {
    current: number;
    total: number;
    percentage: number;
    estimatedMinutesRemaining: number;
  };

  // Configuration
  config: {
    source: string;        // e.g. "Oracle DB"
    sourceTable?: string;  // e.g. "users"
    target: string;        // e.g. "PostgreSQL DWH"
    targetTable?: string;  // e.g. "dim_customer"
    schedule: string;      // e.g. "Hourly · 0 * * * *"
    owner: string;         // e.g. "data-eng@jamkrindo.id"
  };

  // Recent runs (untuk history di drawer)
  recentRuns: JobRun[];
}

export interface JobRun {
  id: string;
  timestamp: string;       // e.g. "Today 18:50"
  status: SyncJobStatus;
  duration?: string;       // e.g. "1m 42s", hanya ada kalau status Success/Failed
}

// ─── Stats untuk summary cards ─────────────────────────────────────────────────

export interface SyncJobsStats {
  total: number;
  running: number;
  successToday: number;
  failedToday: number;
}

// ─── Filter state ──────────────────────────────────────────────────────────────

export type JobStatusFilter = "All" | SyncJobStatus;

export interface SyncJobsFilters {
  status: JobStatusFilter;
  search: string;
  dateRange: [Date | null, Date | null];
}