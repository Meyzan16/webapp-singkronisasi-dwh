"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { FiRefreshCw, FiPauseCircle, FiPlayCircle, FiEye, FiFileText, FiSearch } from "react-icons/fi"; // Add search icon
import DatePicker from "@/components/ui/date-picker"; // Import DatePicker component
import TableComponents from "@/components/ui/table"; // Import TableComponents component

// Sample data for jobs
const jobs = [
  { id: "4800002250", name: "User Data Sync", status: "Running", lastRun: "Today, 06:50 PM", duration: "09:35 - 11:03 PM" },
  { id: "4800002251", name: "Order Sync Process", status: "Success", lastRun: "Today, 06:00 PM", duration: "09:35 - 11:03 PM" },
  { id: "4800002252", name: "Invoice Sync", status: "Failed", lastRun: "Today, 08:00 PM", duration: "08:35 - 11:03 PM" },
  { id: "4800002253", name: "Customer Info Update", status: "Success", lastRun: "Today, 06:30 PM", duration: "09:23 - 11:03 PM" },
  { id: "4800002254", name: "Inventory Sync", status: "Success", lastRun: "Today, 08:00 PM", duration: "08:13 - 11:03 PM" },
  // Additional jobs can be added here
];

// Column definitions
const columns: { name: string; key: "id" | "name" | "status" | "lastRun" | "duration" | "actions" }[] = [
  { name: "Job ID", key: "id" },
  { name: "Job Name", key: "name" },
  { name: "Status", key: "status" },
  { name: "Last Run", key: "lastRun" },
  { name: "Duration", key: "duration" },
  { name: "Actions", key: "actions" },
];

export default function SyncJobsPage() {
  const [activeStatus, setActiveStatus] = useState<"All" | "Running" | "Success" | "Failed">("All");
  const [search, setSearch] = useState("");
  const [dateRange, setDateRange] = useState<[Date | null, Date | null]>([null, null]);

  // Filtering jobs based on search term, status, and date range
  const filteredJobs = useMemo(() => {
    return jobs.filter((job) => {
      const queryMatched =
        job.id.includes(search) ||
        job.name.toLowerCase().includes(search.toLowerCase()) ||
        job.status.toLowerCase().includes(search.toLowerCase());

      const statusMatched = activeStatus === "All" || job.status === activeStatus;

      return queryMatched && statusMatched;
    });
  }, [activeStatus, search, dateRange]);

  // Checkbox handler function for row selection
  const handleCheckboxChange = (id: string, checked: boolean) => {
    console.log("Checkbox changed for: ", id, "checked=", checked);
  };

  // Render action buttons with icons
  const renderActionButtons = (job: any) => (
    <div className="flex items-center gap-2">
      <button
        className="p-2 text-gray-600 hover:text-gray-800 border rounded-lg"
        onClick={() => console.log(`View details for job ${job.id}`)}
      >
        <FiEye size={20} />
      </button>
      <button
        className="p-2 text-gray-600 hover:text-gray-800 border rounded-lg"
        onClick={() => console.log(`Logs for job ${job.id}`)}
      >
        <FiFileText size={20} />
      </button>
      {job.status === "Failed" ? (
        <button
          className="p-2 text-primarygreen hover:text-green-600 border rounded-lg"
          onClick={() => console.log(`Retry job ${job.id}`)}
        >
          <FiRefreshCw size={20} />
        </button>
      ) : job.status === "Running" ? (
        <button
          className="p-2 text-red-600 hover:text-red-800 border rounded-lg"
          onClick={() => console.log(`Stop job ${job.id}`)}
        >
          <FiPauseCircle size={20} />
        </button>
      ) : (
        <button
          className="p-2 text-blue-600 hover:text-blue-800 border rounded-lg"
          onClick={() => console.log(`Re-run job ${job.id}`)}
        >
          <FiPlayCircle size={20} />
        </button>
      )}
    </div>
  );

  return (
    <main className="space-y-6">
      <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Date range picker */}
          <DatePicker value={dateRange} onChange={setDateRange} />

          {/* Search bar */}
          <div className="flex items-center gap-3">
            {/* Updated search bar with icon */}
            <div className="relative">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search jobs..."
                className="px-3 py-2 border rounded-lg w-64 text-sm pr-10"
              />
              {/* Search icon */}
              <FiSearch size={20} className="absolute top-1/2 right-3 transform -translate-y-1/2 text-gray-500" />
            </div>
            <Button variant="secondary" size="md" className="text-sm" onClick={() => setSearch("")}>
              Reset
            </Button>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        {/* Filter section */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 mb-4">
          {/* Status buttons */}
          <div className="flex items-center gap-2 mb-2">
            {["All", "Running", "Success", "Failed"].map((status) => (
              <button
                key={status}
                onClick={() => setActiveStatus(status as "All" | "Running" | "Success" | "Failed")}
                className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                  activeStatus === status
                    ? "bg-primarygreen text-white"
                    : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                }`}
              >
                {status}
              </button>
            ))}
          </div>
        </div>

        {/* Table displaying filtered jobs */}
        <TableComponents
          data={filteredJobs}
          columns={columns}
          onRowCheckboxChange={handleCheckboxChange}
          renderActionButtons={renderActionButtons}
        />
      </section>
    </main>
  );
}