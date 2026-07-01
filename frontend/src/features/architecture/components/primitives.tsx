// Shared UI primitives for architecture page components

export function Code({ children }: { children: string }) {
  return (
    <pre className="bg-neutral-900 text-green-400 text-[11px] font-mono p-3 rounded-lg overflow-x-auto leading-relaxed whitespace-pre-wrap">
      {children}
    </pre>
  );
}

export function Badge({ label, color }: { label: string; color: string }) {
  return <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${color}`}>{label}</span>;
}

export function SectionTitle({ icon, title, sub }: { icon: string; title: string; sub?: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className="text-2xl">{icon}</span>
      <div>
        <h2 className="text-lg font-bold text-neutral-900">{title}</h2>
        {sub && <p className="text-xs text-neutral-500">{sub}</p>}
      </div>
    </div>
  );
}

export function LiveBadge({ live, loading }: { live: boolean; loading?: boolean }) {
  if (loading) {
    return (
      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-neutral-100 text-neutral-400 inline-flex items-center gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-neutral-300 animate-pulse" /> memuat…
      </span>
    );
  }
  return live ? (
    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-green-100 text-green-700 inline-flex items-center gap-1">
      <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" /> Live dari agent
    </span>
  ) : (
    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-neutral-100 text-neutral-500 inline-flex items-center gap-1">
      <span className="w-1.5 h-1.5 rounded-full bg-neutral-400" /> Static (fallback)
    </span>
  );
}

/** PLAN_v5 Group C7 — badge showing whether a field is DB-editable or still hardcoded. */
export function SourceBadge({ dbKey, dbKeys }: { dbKey: string; dbKeys: Set<string> }) {
  const inDb = dbKeys.has(dbKey);
  return inDb ? (
    <a href="/settings" title={`Editable via Settings > Agent Config (${dbKey})`}
       className="text-[8px] font-bold px-1 py-0.5 rounded bg-blue-50 text-blue-600 hover:bg-blue-100 ml-1">
      🔵 DB
    </a>
  ) : (
    <span title="Hardcoded constant — belum bisa diubah dari UI"
          className="text-[8px] font-bold px-1 py-0.5 rounded bg-neutral-100 text-neutral-400 ml-1">
      ⚪ static
    </span>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (t: string) => void }) {
  return (
    <div className="flex bg-neutral-100 rounded-lg p-0.5 gap-0.5 mb-4 flex-wrap">
      {tabs.map(t => (
        <button key={t} onClick={() => onChange(t)}
          className={`flex-1 py-1.5 rounded-md text-xs font-semibold transition-all min-w-[80px] ${
            active === t ? "bg-white shadow text-neutral-900" : "text-neutral-500 hover:text-neutral-700"
          }`}>
          {t}
        </button>
      ))}
    </div>
  );
}
