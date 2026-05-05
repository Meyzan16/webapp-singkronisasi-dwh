import { FieldTypeBucket } from "@/types/data-mapping";

interface FieldTypeBreakdownProps {
  buckets: FieldTypeBucket[];
}

export default function FieldTypeBreakdown({ buckets }: FieldTypeBreakdownProps) {
  const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-3 text-sm font-medium text-gray-900">Field type breakdown</div>

      <div className="space-y-2.5">
        {buckets.map((bucket) => {
          const percentage = total > 0 ? Math.round((bucket.count / total) * 100) : 0;

          return (
            <div key={bucket.label}>
              <div className="mb-1 flex items-center justify-between text-[11px]">
                <span className="flex items-center gap-1.5 text-gray-700">
                  <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: bucket.color }} />
                  {bucket.label}
                </span>
                <span className="text-gray-500">{bucket.count}</span>
              </div>
              <div className="h-1.5 rounded-full bg-gray-100">
                <div
                  className="h-1.5 rounded-full"
                  style={{ width: `${percentage}%`, backgroundColor: bucket.color }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
