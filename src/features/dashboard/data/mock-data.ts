// src/features/dashboard/data/mock-data.ts

import {
  DashboardStats,
  OpsMetrics,
  DailyActivity,
  ErrorBucket,
  DataSource,
  UpcomingJob,
  DashboardNotification,
  RecentSyncJob,
} from "@/types/dashboard";

export const dashboardStats: DashboardStats = {
  totalJobs: 128,
  totalJobsDelta: 12,
  running: 7,
  recordsSyncedToday: 2_340_000,
  avgRecordsPerSec: 850,
  failedToday: 3,
};

export const opsMetrics: OpsMetrics = {
  avgSyncLagSeconds: 252,        // 4m 12s
  syncLagSlaSeconds: 600,        // 10 menit
  dataFreshness: "18:45",
  queueBacklog: 12,
  queueClearEstimateMinutes: 18,
};

export const weeklyActivity: DailyActivity[] = [
  { day: "Mon", success: 28, failed: 2 },
  { day: "Tue", success: 34, failed: 1 },
  { day: "Wed", success: 30, failed: 2 },
  { day: "Thu", success: 38, failed: 1 },
  { day: "Fri", success: 32, failed: 2 },
  { day: "Sat", success: 36, failed: 1 },
  { day: "Sun", success: 31, failed: 2 },
];

export const errorBuckets: ErrorBucket[] = [
  { category: "Connection timeout", count: 2, color: "#DC2626" },
  { category: "Schema mismatch", count: 1, color: "#F59E0B" },
  { category: "Auth error", count: 0, color: "#9CA3AF" },
];

export const dataSources: DataSource[] = [
  { id: "ds-1", name: "Oracle DB", status: "Online", lastPing: "2m ago" },
  { id: "ds-2", name: "PostgreSQL DWH", status: "Online", lastPing: "1m ago" },
  { id: "ds-3", name: "SAP HANA", status: "Slow", lastPing: "Slow response" },
  { id: "ds-4", name: "REST API Gateway", status: "Offline", lastPing: "Timeout 5m ago" },
];

export const upcomingJobs: UpcomingJob[] = [
  {
    id: "up-1",
    name: "User Data Sync",
    scheduledAt: "19:00",
    inMinutes: 12,
    schedule: "Hourly",
    source: "Oracle",
    target: "DWH",
  },
  {
    id: "up-2",
    name: "Inventory Snapshot",
    scheduledAt: "19:16",
    inMinutes: 28,
    schedule: "Every 30m",
    source: "SAP",
    target: "DWH",
  },
  {
    id: "up-3",
    name: "Customer Refresh",
    scheduledAt: "19:33",
    inMinutes: 45,
    schedule: "Daily 19:33",
    source: "Oracle",
    target: "DWH",
  },
];

export const recentJobs: RecentSyncJob[] = [
  { id: "4800002250", name: "User Data Sync", status: "Running", lastRun: "06:50 PM", records: 12_402 },
  { id: "4800002251", name: "Order Sync Process", status: "Success", lastRun: "06:00 PM", records: 2_341 },
  { id: "4800002252", name: "Invoice Sync", status: "Failed", lastRun: "05:00 PM", records: 0 },
  { id: "4800002253", name: "Customer Info Update", status: "Success", lastRun: "04:30 PM", records: 847 },
];

export const notifications: DashboardNotification[] = [
  { id: "n-1", severity: "error", title: "Invoice Sync failed", detail: "Connection timeout · 5m ago" },
  { id: "n-2", severity: "warning", title: "SAP HANA slow response", detail: "Avg 8.2s · 12m ago" },
  { id: "n-3", severity: "success", title: "Order Sync completed", detail: "2,341 records · 1h ago" },
  { id: "n-4", severity: "info", title: "Schedule updated", detail: "User Data Sync · 2h ago" },
];