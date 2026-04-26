// src/features/dashboard/components/activity-chart.tsx

import { DailyActivity } from "@/types/dashboard";

interface ActivityChartProps {
  data: DailyActivity[];
}

// Layout chart
const CHART_WIDTH = 380;
const CHART_HEIGHT = 150;
const PADDING_LEFT = 30;
const PADDING_TOP = 20;
const PADDING_BOTTOM = 25;
const BAR_WIDTH = 22;

export default function ActivityChart({ data }: ActivityChartProps) {
  const maxValue = Math.max(
    ...data.map((d) => d.success + d.failed),
    10  // floor minimum supaya grafik tidak terlalu mepet
  );
  const niceMax = Math.ceil(maxValue / 10) * 10;

  const innerHeight = CHART_HEIGHT - PADDING_TOP - PADDING_BOTTOM;
  const chartAreaWidth = CHART_WIDTH - PADDING_LEFT - 10;
  const slotWidth = chartAreaWidth / data.length;

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-medium text-gray-900">
          Sync activity (last 7 days)
        </div>
        <div className="flex items-center gap-3 text-[11px] text-gray-500">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-primarygreen" />
            Success
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-rose-500" />
            Failed
          </span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        className="h-[150px] w-full"
        role="img"
        aria-label="Bar chart of sync activity over the last 7 days"
      >
        {/* Axes */}
        <line
          x1={PADDING_LEFT}
          y1={PADDING_TOP}
          x2={PADDING_LEFT}
          y2={CHART_HEIGHT - PADDING_BOTTOM}
          stroke="#E5E7EB"
          strokeWidth={0.5}
        />
        <line
          x1={PADDING_LEFT}
          y1={CHART_HEIGHT - PADDING_BOTTOM}
          x2={CHART_WIDTH - 10}
          y2={CHART_HEIGHT - PADDING_BOTTOM}
          stroke="#E5E7EB"
          strokeWidth={0.5}
        />

        {/* Y-axis labels */}
        <text x={PADDING_LEFT - 8} y={PADDING_TOP + 4} textAnchor="end" fontSize={9} fill="#9CA3AF">
          {niceMax}
        </text>
        <text x={PADDING_LEFT - 8} y={PADDING_TOP + innerHeight / 2 + 3} textAnchor="end" fontSize={9} fill="#9CA3AF">
          {Math.round(niceMax / 2)}
        </text>
        <text x={PADDING_LEFT - 8} y={CHART_HEIGHT - PADDING_BOTTOM + 3} textAnchor="end" fontSize={9} fill="#9CA3AF">
          0
        </text>

        {/* Bars */}
        {data.map((d, i) => {
          const total = d.success + d.failed;
          const totalHeight = (total / niceMax) * innerHeight;
          const failedHeight = (d.failed / niceMax) * innerHeight;
          const successHeight = totalHeight - failedHeight;

          const xCenter = PADDING_LEFT + slotWidth * i + slotWidth / 2;
          const barX = xCenter - BAR_WIDTH / 2;
          const baseY = CHART_HEIGHT - PADDING_BOTTOM;

          return (
            <g key={d.day}>
              {/* Success (bottom) */}
              <rect
                x={barX}
                y={baseY - successHeight}
                width={BAR_WIDTH}
                height={successHeight}
                rx={2}
                fill="#14b8a6"
              />
              {/* Failed (stack on top) */}
              {d.failed > 0 && (
                <rect
                  x={barX}
                  y={baseY - successHeight - failedHeight}
                  width={BAR_WIDTH}
                  height={failedHeight}
                  rx={2}
                  fill="#DC2626"
                />
              )}
              {/* Day label */}
              <text
                x={xCenter}
                y={CHART_HEIGHT - 10}
                textAnchor="middle"
                fontSize={9}
                fill="#9CA3AF"
              >
                {d.day}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}