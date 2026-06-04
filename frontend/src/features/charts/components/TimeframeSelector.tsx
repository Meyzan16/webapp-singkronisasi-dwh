interface TimeframeSelectorProps {
  selectedTF: string;
  onSelect: (tf: string) => void;
  timeframes: string[];
}

export function TimeframeSelector({ selectedTF, onSelect, timeframes }: TimeframeSelectorProps) {
  return (
    <div>
      <label className="text-sm font-semibold block mb-2">Timeframe</label>
      <div className="grid grid-cols-4 gap-2">
        {timeframes.map((tf) => (
          <button
            key={tf}
            onClick={() => onSelect(tf)}
            className={`p-2 rounded-lg text-sm font-medium ${
              selectedTF === tf ? "bg-primarygreen text-white" : "bg-neutral-100"
            }`}
          >
            {tf.toUpperCase()}
          </button>
        ))}
      </div>
    </div>
  );
}
