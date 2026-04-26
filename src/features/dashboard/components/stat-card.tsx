// src/features/dashboard/components/stat-card.tsx

import React from "react";

interface StatCardProps {
  label: string;
  value: string | number;
  hint?: string;
  hintTone?: "default" | "success" | "danger" | "muted";
  accent?: boolean;            // border kiri primarygreen
  valueTone?: "default" | "success" | "danger";
  liveDot?: boolean;           // titik hijau berdenyut untuk "Running"
}

const hintToneClasses: Record<NonNullable<StatCardProps["hintTone"]>, string> = {
  default: "text-gray-500",
  success: "text-primarygreen",
  danger: "text-rose-600",
  muted: "text-gray-400",
};

const valueToneClasses: Record<NonNullable<StatCardProps["valueTone"]>, string> = {
  default: "text-gray-900",
  success: "text-primarygreen",
  danger: "text-rose-600",
};

export default function StatCard({
  label,
  value,
  hint,
  hintTone = "muted",
  accent = false,
  valueTone = "default",
  liveDot = false,
}: StatCardProps) {
  return (
    <div
      className={`rounded-xl border border-gray-200 bg-white p-4 ${
        accent ? "border-l-[3px] border-l-primarygreen" : ""
      }`}
    >
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`mt-1.5 text-2xl font-medium ${valueToneClasses[valueTone]}`}>
        {value}
      </div>
      {hint && (
        <div className={`mt-1 flex items-center gap-1 text-[11px] ${hintToneClasses[hintTone]}`}>
          {liveDot && (
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primarygreen opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primarygreen" />
            </span>
          )}
          <span>{hint}</span>
        </div>
      )}
    </div>
  );
}