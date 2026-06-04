interface ScannerFiltersProps {
  search:    string;
  alertType: string;
  minProb:   number;
  minRR:     number;
  resultCount: number;
  totalCount:  number;
  onSearch:    (v: string) => void;
  onAlertType: (v: string) => void;
  onMinProb:   (v: number) => void;
  onMinRR:     (v: number) => void;
}

const ALERT_TYPES = [
  { key: "ALL",          label: "Semua",       dot: "bg-neutral-500" },
  { key: "squeeze",      label: "⚡ Squeeze",   dot: "bg-purple-500"  },
  { key: "accumulation", label: "📦 Accum",    dot: "bg-teal-500"    },
  { key: "breakout",     label: "🎯 Breakout",  dot: "bg-yellow-500"  },
  { key: "reversal",     label: "↩ Reversal",  dot: "bg-blue-500"    },
];

const PROB_OPTIONS = [
  { value: 0,  label: "Semua prob" },
  { value: 50, label: "≥ 50%"      },
  { value: 70, label: "≥ 70%"      },
  { value: 80, label: "≥ 80%"      },
];

const RR_OPTIONS = [
  { value: 3,  label: "R:R ≥ 1:3" },
  { value: 4,  label: "R:R ≥ 1:4" },
  { value: 5,  label: "R:R ≥ 1:5" },
  { value: 7,  label: "R:R ≥ 1:7" },
];

export function ScannerFilters({
  search, alertType, minProb, minRR, resultCount, totalCount,
  onSearch, onAlertType, onMinProb, onMinRR,
}: ScannerFiltersProps) {
  return (
    <div className="space-y-2">
      {/* Row 1: search + min prob + min R:R */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Search */}
        <div className="relative flex-1 min-w-[140px]">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-400 text-xs">🔍</span>
          <input
            type="text"
            placeholder="Cari symbol…"
            value={search}
            onChange={e => onSearch(e.target.value)}
            className="w-full pl-7 pr-8 py-1.5 bg-neutral-800 border border-neutral-700 rounded-lg text-xs text-white placeholder-neutral-500 focus:outline-none focus:border-teal-500"
          />
          {search && (
            <button onClick={() => onSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-white text-xs">
              ✕
            </button>
          )}
        </div>

        {/* Min R:R — always visible, default 1:3 */}
        <select
          value={minRR}
          onChange={e => onMinRR(Number(e.target.value))}
          className="px-2.5 py-1.5 bg-teal-900/40 border border-teal-700/60 rounded-lg text-xs text-teal-300 font-semibold focus:outline-none focus:border-teal-400 cursor-pointer">
          {RR_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        {/* Min probability */}
        <select
          value={minProb}
          onChange={e => onMinProb(Number(e.target.value))}
          className="px-2.5 py-1.5 bg-neutral-800 border border-neutral-700 rounded-lg text-xs text-white focus:outline-none focus:border-teal-500 cursor-pointer">
          {PROB_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        {/* Result count */}
        {resultCount < totalCount && (
          <span className="text-[10px] text-neutral-500 ml-auto">
            {resultCount} / {totalCount} hasil
          </span>
        )}
      </div>

      {/* Row 2: alert type chips */}
      <div className="flex gap-1.5 flex-wrap">
        {ALERT_TYPES.map(a => (
          <button key={a.key} onClick={() => onAlertType(a.key)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold transition-colors ${
              alertType === a.key
                ? "bg-teal-600 text-white"
                : "bg-neutral-800 text-neutral-400 hover:text-white hover:bg-neutral-700"
            }`}>
            {a.key !== "ALL" && <span className={`w-1.5 h-1.5 rounded-full ${a.dot}`} />}
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}
