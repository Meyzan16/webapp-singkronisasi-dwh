const STYLES = [
  { key: "scalping",   label: "Scalping",  icon: "⚡", desc: "15m · Menit–Jam",   hint: "RSI ekstrem, vol spike, momentum cepat"    },
  { key: "daytrading", label: "Day Trade", icon: "📅", desc: "1H · Harian",       hint: "Balance trend & momentum, intraday setup"  },
  { key: "swing",      label: "Swing",     icon: "🌊", desc: "4H · Hari–Minggu",  hint: "BB squeeze, akumulasi, breakout multi-hari" },
  { key: "position",   label: "Position",  icon: "🏔", desc: "1D · Minggu–Bulan", hint: "Akumulasi panjang, trend makro, S/R weekly" },
];

interface StyleSelectorProps {
  active: string;
  onChange: (key: string) => void;
}

export function StyleSelector({ active, onChange }: StyleSelectorProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
      {STYLES.map(s => (
        <button key={s.key} onClick={() => onChange(s.key)} title={s.hint}
          className={`flex flex-col items-start px-3 py-2 rounded-xl border text-left transition-all ${
            active === s.key
              ? "bg-teal-600 border-teal-500 text-white shadow-sm"
              : "bg-neutral-800 border-neutral-700 text-neutral-400 hover:border-teal-600/50 hover:text-neutral-100"
          }`}>
          <div className="flex items-center gap-1.5">
            <span className="text-base">{s.icon}</span>
            <span className="font-bold text-xs">{s.label}</span>
          </div>
          <span className={`text-[10px] mt-0.5 leading-tight ${active === s.key ? "opacity-80" : "opacity-50"}`}>
            {s.desc}
          </span>
        </button>
      ))}
    </div>
  );
}
