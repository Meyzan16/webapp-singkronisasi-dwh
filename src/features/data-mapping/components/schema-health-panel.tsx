import { SchemaHealth } from "@/types/data-mapping";

interface SchemaHealthPanelProps {
  schemas: SchemaHealth[];
}

const statusStyles: Record<SchemaHealth["status"], string> = {
  Healthy: "bg-emerald-50 text-emerald-700",
  Warning: "bg-amber-50 text-amber-700",
  Critical: "bg-rose-50 text-rose-700",
};

export default function SchemaHealthPanel({ schemas }: SchemaHealthPanelProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-3 text-sm font-medium text-gray-900">Schema health</div>

      <div className="flex flex-col">
        {schemas.map((schema, index) => (
          <div
            key={schema.id}
            className={`py-2 ${index < schemas.length - 1 ? "border-b border-gray-100" : ""}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[13px] font-medium text-gray-900">{schema.system}</div>
                <div className="mt-0.5 text-[11px] text-gray-400">{schema.object}</div>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-[11px] ${statusStyles[schema.status]}`}>
                {schema.status}
              </span>
            </div>

            <div className="mt-2 flex items-center gap-2">
              <div className="h-1.5 flex-1 rounded-full bg-gray-100">
                <div className="h-1.5 rounded-full bg-primarygreen" style={{ width: `${schema.coverage}%` }} />
              </div>
              <span className="w-8 text-right text-[11px] text-gray-500">{schema.coverage}%</span>
            </div>

            <div className="mt-1 flex justify-between text-[11px] text-gray-400">
              <span>{schema.drift} drift fields</span>
              <span>{schema.lastScan}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
