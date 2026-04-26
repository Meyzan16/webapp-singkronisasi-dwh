// src/features/dashboard/components/error-breakdown.tsx

import { ErrorBucket } from "@/types/dashboard";

interface ErrorBreakdownProps {
  buckets: ErrorBucket[];
}

const CIRCUMFERENCE = 2 * Math.PI * 32; // r = 32

export default function ErrorBreakdown({ buckets }: ErrorBreakdownProps) {
  const total = buckets.reduce((sum, b) => sum + b.count, 0);

  // Hitung dasharray + offset secara akumulatif
  let cumulative = 0;
  const segments = buckets.map((bucket) => {
    const fraction = total > 0 ? bucket.count / total : 0;
    const length = fraction * CIRCUMFERENCE;
    const offset = -cumulative;
    cumulative += length;
    return { ...bucket, length, offset };
  });

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-3 text-sm font-medium text-gray-900">
        Error breakdown (today)
      </div>

      <div className="flex items-center gap-3">
        {/* Donut */}
        <svg viewBox="0 0 80 80" className="h-20 w-20 shrink-0" role="img" aria-label="Error category breakdown donut chart">
          {/* Track */}
          <circle cx="40" cy="40" r="32" fill="none" stroke="#F3F4F6" strokeWidth={12} />

          {/* Segmen */}
          {total > 0 &&
            segments.map((seg) => (
              <circle
                key={seg.category}
                cx="40"
                cy="40"
                r="32"
                fill="none"
                stroke={seg.color}
                strokeWidth={12}
                strokeDasharray={`${seg.length} ${CIRCUMFERENCE - seg.length}`}
                strokeDashoffset={seg.offset}
                transform="rotate(-90 40 40)"
              />
            ))}

          {/* Total di tengah */}
          <text
            x={40}
            y={44}
            textAnchor="middle"
            fontSize={14}
            fontWeight={500}
            fill="#111827"
          >
            {total}
          </text>
        </svg>

        {/* Legend */}
        <div className="flex-1 text-[11px]">
          {buckets.map((bucket) => (
            <div
              key={bucket.category}
              className="flex items-center justify-between py-0.5"
            >
              <span className="flex items-center gap-1.5 text-gray-700">
                <span
                  className="h-2 w-2 rounded-sm"
                  style={{ backgroundColor: bucket.color }}
                />
                {bucket.category}
              </span>
              <span className="text-gray-500">{bucket.count}</span>
            </div>
          ))}
        </div>
      </div>

      <button
        className="mt-3 w-full border-t border-gray-100 pt-2 text-left text-[11px] text-primarygreen hover:underline"
        type="button"
      >
        View error logs →
      </button>
    </div>
  );
}