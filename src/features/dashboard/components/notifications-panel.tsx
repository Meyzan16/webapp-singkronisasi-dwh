// src/features/dashboard/components/notifications-panel.tsx

import { DashboardNotification, NotificationSeverity } from "@/types/dashboard";

interface NotificationsPanelProps {
  notifications: DashboardNotification[];
}

const severityDotColor: Record<NotificationSeverity, string> = {
  error: "bg-rose-500",
  warning: "bg-amber-500",
  success: "bg-primarygreen",
  info: "bg-gray-400",
};

export default function NotificationsPanel({ notifications }: NotificationsPanelProps) {
  // Hitung "new" = error + warning
  const newCount = notifications.filter(
    (n) => n.severity === "error" || n.severity === "warning"
  ).length;

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-medium text-gray-900">Notifications</div>
        {newCount > 0 && (
          <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] text-rose-700">
            {newCount} new
          </span>
        )}
      </div>

      <div className="flex flex-col">
        {notifications.map((n, idx) => (
          <div
            key={n.id}
            className={`flex gap-2.5 py-2.5 ${
              idx < notifications.length - 1 ? "border-b border-gray-100" : ""
            }`}
          >
            <span
              className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${severityDotColor[n.severity]}`}
            />
            <div className="min-w-0">
              <div className="truncate text-xs text-gray-900">{n.title}</div>
              <div className="mt-0.5 text-[11px] text-gray-400">{n.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}