type Direction = "ALL" | "LONG" | "SHORT";

interface DirectionFilterProps {
  active: Direction;
  total: number;
  longCount: number;
  shortCount: number;
  onChange: (d: Direction) => void;
}

export function DirectionFilter({ active, total, longCount, shortCount, onChange }: DirectionFilterProps) {
  const OPTIONS: { key: Direction; label: string }[] = [
    { key: "ALL",   label: `All (${total})`         },
    { key: "LONG",  label: `▲ Long (${longCount})`  },
    { key: "SHORT", label: `▼ Short (${shortCount})` },
  ];

  return (
    <div className="flex items-center gap-2">
      {OPTIONS.map(({ key, label }) => (
        <button key={key} onClick={() => onChange(key)}
          className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors ${
            active === key
              ? key === "LONG"  ? "bg-green-600 text-white"
              : key === "SHORT" ? "bg-red-600 text-white"
              : "bg-teal-600 text-white"
              : "bg-neutral-800 text-neutral-400 hover:text-white"
          }`}>
          {label}
        </button>
      ))}
    </div>
  );
}
