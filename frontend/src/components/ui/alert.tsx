"use client";

import { createPortal } from "react-dom";
import { useContext, useCallback, useEffect, useMemo, useRef } from "react";
import { GlobalContext } from "@/app/context";
import type { AlertSeverity } from "@/app/context";

// ─── Config ───────────────────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<AlertSeverity, string> = {
  success: "bg-emerald-500 text-white",
  error:   "bg-red-500 text-white",
  warning: "bg-amber-400 text-black",
  info:    "bg-blue-500 text-white",
};

const SEVERITY_ICONS: Record<AlertSeverity, string> = {
  success: "✅",
  error:   "❌",
  warning: "⚠️",
  info:    "ℹ️",
};

// error = 0 → no auto-dismiss, user must close manually
const DISMISS_DURATION: Record<AlertSeverity, number> = {
  success: 3000,
  info:    3000,
  warning: 5000,
  error:   0,
};

// ─── Component ────────────────────────────────────────────────────────────────

const AlertComponent = () => {
  const { openAlert, setOpenAlert } = useContext(GlobalContext)!;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isVisible = useMemo(
    () => Boolean(openAlert.status && openAlert.severity),
    [openAlert.status, openAlert.severity]
  );

  const dismiss = useCallback(() => {
    setOpenAlert({ status: false, message: "", severity: "" });
  }, [setOpenAlert]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!openAlert.status || !openAlert.severity) return;

    const duration = DISMISS_DURATION[openAlert.severity as AlertSeverity];
    if (duration === 0) return; // error — manual dismiss only

    timerRef.current = setTimeout(dismiss, duration);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [openAlert.status, openAlert.severity, dismiss]);

  if (!isVisible) return null;

  const severity = openAlert.severity as AlertSeverity;

  return createPortal(
    <div
      role="alert"
      aria-live="assertive"
      className={`fixed left-1/2 top-0 z-[9999] -translate-x-1/2 translate-y-6 opacity-100
        ${SEVERITY_STYLES[severity]}
        flex items-center gap-3 rounded-full px-5 py-3 shadow-lg`}
    >
      <span>{SEVERITY_ICONS[severity]}</span>
      <span className="text-sm font-medium">{openAlert.message}</span>
      <button
        onClick={dismiss}
        aria-label="Close alert"
        className="ml-2 text-current opacity-70 hover:opacity-100 transition-opacity text-lg leading-none"
      >
        ×
      </button>
    </div>,
    document.body
  );
};

export default AlertComponent;
