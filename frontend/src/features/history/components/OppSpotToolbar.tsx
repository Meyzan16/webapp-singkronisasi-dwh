"use client";

interface OppSpotToolbarProps {
  positionCount:   number;
  loading:         boolean;
  countdown:       number;
  lastUpdated:     Date | null;
  notifPermission: NotificationPermission | "default";
  onExport:        () => void;
  onRefresh:       () => void;
  onRequestNotif:  () => void;
}

export function OppSpotToolbar({
  positionCount, loading, countdown, lastUpdated,
  notifPermission, onExport, onRefresh, onRequestNotif,
}: OppSpotToolbarProps) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button
        onClick={onExport}
        disabled={positionCount === 0}
        className="text-xs border border-neutral-200 rounded-lg px-3 py-1.5 bg-white text-neutral-600 hover:text-teal-600 hover:border-teal-300 transition-colors font-semibold disabled:opacity-40"
      >
        ⬇ Export CSV
      </button>

      {typeof window !== "undefined" && "Notification" in window && notifPermission !== "granted" && (
        <button
          onClick={onRequestNotif}
          className="text-xs border border-neutral-200 rounded-lg px-3 py-1.5 bg-white text-neutral-600 hover:text-yellow-600 hover:border-yellow-300 transition-colors font-semibold"
        >
          🔔 Aktifkan Notifikasi
        </button>
      )}
      {notifPermission === "granted" && (
        <span className="text-[10px] text-green-600 font-semibold">🔔 Notifikasi aktif</span>
      )}

      <div className="ml-auto flex items-center gap-2">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-green-50 border border-green-200">
          <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
          <span className="text-[10px] font-bold text-green-700">LIVE</span>
          <span className="text-[10px] text-green-600 tabular-nums">{countdown}s</span>
        </div>
        {lastUpdated && (
          <p className="text-[10px] text-neutral-400">{lastUpdated.toLocaleTimeString()}</p>
        )}
        <button
          onClick={onRefresh}
          disabled={loading}
          className="text-xs text-teal-600 hover:text-teal-500 font-semibold disabled:opacity-40"
        >
          {loading ? "..." : "↺"}
        </button>
      </div>
    </div>
  );
}
