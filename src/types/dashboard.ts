// src/types/dashboard.ts

import { SyncJob } from "./sync-jobs";

// ─── Stat cards ───────────────────────────────────────────────────────────────

export interface DashboardStats {
  totalJobs: number;
  totalJobsDelta: number;       // selisih vs kemarin
  running: number;
  recordsSyncedToday: number;   // total record hari ini
  avgRecordsPerSec: number;
  failedToday: number;
}

// ─── Metrik operasional ──────────────────────────────────────────────────────

export interface OpsMetrics {
  avgSyncLagSeconds: number;    // dalam detik, di-format di UI
  syncLagSlaSeconds: number;    // target SLA (mis. 600 = 10 menit)
  dataFreshness: string;        // jam terakhir update sukses, mis. "18:45"
  queueBacklog: number;
  queueClearEstimateMinutes: number;
}

// ─── Activity chart ──────────────────────────────────────────────────────────

export interface DailyActivity {
  day: string;       // "Mon", "Tue", ...
  success: number;
  failed: number;
}

// ─── Error breakdown ─────────────────────────────────────────────────────────

export type ErrorCategory = "Connection timeout" | "Schema mismatch" | "Auth error";

export interface ErrorBucket {
  category: ErrorCategory;
  count: number;
  color: string;     // hex untuk donut chart
}

// ─── Data sources ────────────────────────────────────────────────────────────

export type DataSourceStatus = "Online" | "Slow" | "Offline";

export interface DataSource {
  id: string;
  name: string;
  status: DataSourceStatus;
  lastPing: string;  // human-readable, mis. "2m ago"
}

// ─── Upcoming jobs ───────────────────────────────────────────────────────────

export interface UpcomingJob {
  id: string;
  name: string;
  scheduledAt: string;       // mis. "19:00"
  inMinutes: number;         // countdown
  schedule: string;          // mis. "Hourly"
  source: string;            // mis. "Oracle"
  target: string;            // mis. "DWH"
}

// ─── Notifications ───────────────────────────────────────────────────────────

export type NotificationSeverity = "error" | "warning" | "success" | "info";

export interface DashboardNotification {
  id: string;
  severity: NotificationSeverity;
  title: string;
  detail: string;             // mis. "Connection timeout · 5m ago"
}

// ─── Recent job baris (extends SyncJob dengan records) ───────────────────────

export interface RecentSyncJob extends Pick<SyncJob, "id" | "name" | "status" | "lastRun"> {
  records: number;
}