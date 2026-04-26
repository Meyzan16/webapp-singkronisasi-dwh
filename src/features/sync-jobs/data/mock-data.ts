// src/features/sync-jobs/data/mock-data.ts

import { SyncJobDetail, SyncJobsStats } from "@/types/sync-jobs-extended";

export const syncJobsStats: SyncJobsStats = {
  total: 128,
  running: 7,
  successToday: 42,
  failedToday: 3,
};

export const syncJobsData: SyncJobDetail[] = [
  {
    id: "4800002250",
    name: "User Data Sync",
    status: "Running",
    lastRun: "Today, 06:50 PM",
    duration: "09:35 - 11:03 PM",
    progress: {
      current: 12402,
      total: 18000,
      percentage: 68,
      estimatedMinutesRemaining: 3,
    },
    config: {
      source: "Oracle DB",
      sourceTable: "users",
      target: "PostgreSQL DWH",
      targetTable: "dim_customer",
      schedule: "Hourly · 0 * * * *",
      owner: "data-eng@jamkrindo.id",
    },
    recentRuns: [
      { id: "r1", timestamp: "Today 18:50", status: "Running" },
      { id: "r2", timestamp: "Today 17:50", status: "Success", duration: "1m 42s" },
      { id: "r3", timestamp: "Today 16:50", status: "Success", duration: "1m 28s" },
    ],
  },
  {
    id: "4800002251",
    name: "Order Sync Process",
    status: "Success",
    lastRun: "Today, 06:00 PM",
    duration: "09:35 - 11:03 PM",
    config: {
      source: "Oracle DB",
      sourceTable: "orders",
      target: "PostgreSQL DWH",
      targetTable: "fact_sales",
      schedule: "Every 30m · */30 * * * *",
      owner: "data-eng@jamkrindo.id",
    },
    recentRuns: [
      { id: "r1", timestamp: "Today 18:00", status: "Success", duration: "2m 15s" },
      { id: "r2", timestamp: "Today 17:30", status: "Success", duration: "1m 58s" },
      { id: "r3", timestamp: "Today 17:00", status: "Success", duration: "2m 03s" },
    ],
  },
  {
    id: "4800002252",
    name: "Invoice Sync",
    status: "Failed",
    lastRun: "Today, 08:00 PM",
    duration: "08:35 - 11:03 PM",
    config: {
      source: "SAP HANA",
      sourceTable: "invoices",
      target: "PostgreSQL DWH",
      targetTable: "fact_billing",
      schedule: "Daily · 0 8 * * *",
      owner: "data-eng@jamkrindo.id",
    },
    recentRuns: [
      { id: "r1", timestamp: "Today 20:00", status: "Failed", duration: "0s" },
      { id: "r2", timestamp: "Yesterday 20:00", status: "Failed", duration: "0s" },
      { id: "r3", timestamp: "2 days ago", status: "Success", duration: "3m 12s" },
    ],
  },
  {
    id: "4800002253",
    name: "Customer Info Update",
    status: "Success",
    lastRun: "Today, 06:30 PM",
    duration: "09:23 - 11:03 PM",
    config: {
      source: "Oracle DB",
      sourceTable: "customers",
      target: "PostgreSQL DWH",
      targetTable: "dim_customer",
      schedule: "Every 2 hours · 0 */2 * * *",
      owner: "ops@jamkrindo.id",
    },
    recentRuns: [
      { id: "r1", timestamp: "Today 18:30", status: "Success", duration: "1m 12s" },
      { id: "r2", timestamp: "Today 16:30", status: "Success", duration: "1m 08s" },
      { id: "r3", timestamp: "Today 14:30", status: "Success", duration: "1m 15s" },
    ],
  },
  {
    id: "4800002254",
    name: "Inventory Sync",
    status: "Success",
    lastRun: "Today, 08:00 PM",
    duration: "08:13 - 11:03 PM",
    config: {
      source: "SAP HANA",
      sourceTable: "stock",
      target: "PostgreSQL DWH",
      targetTable: "stock_snapshot",
      schedule: "Every 15m · */15 * * * *",
      owner: "data-eng@jamkrindo.id",
    },
    recentRuns: [
      { id: "r1", timestamp: "Today 20:00", status: "Success", duration: "45s" },
      { id: "r2", timestamp: "Today 19:45", status: "Success", duration: "42s" },
      { id: "r3", timestamp: "Today 19:30", status: "Success", duration: "48s" },
    ],
  },
];