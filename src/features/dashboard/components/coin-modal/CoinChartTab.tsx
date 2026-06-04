import { TradingChart } from "@/components/ui/trading-chart";
import type { Candle, Analysis } from "./types";

interface CoinChartTabProps {
  candles: Candle[];
  loading: boolean;
  analysis: Analysis | null;
  chartTf: string;
  onTfChange: (tf: string) => void;
}

const TIMEFRAMES = ["15m", "1h", "4h", "1d", "1w"] as const;

export function CoinChartTab({ candles, loading, analysis, chartTf, onTfChange }: CoinChartTabProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {TIMEFRAMES.map(tf => (
            <button key={tf} onClick={() => onTfChange(tf)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors ${
                chartTf === tf ? "bg-primarygreen text-white" : "bg-neutral-100 hover:bg-neutral-200"
              }`}>
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
        {loading && <span className="text-xs text-muted-foreground animate-pulse">Loading...</span>}
      </div>

      {candles.length > 0 && !loading && (
        <TradingChart
          candles={candles}
          height={380}
          entryPrice={analysis?.entry ?? undefined}
          entryZoneLow={analysis?.entry_zone_low ?? undefined}
          entryZoneHigh={analysis?.entry_zone_high ?? undefined}
          stopLoss={analysis?.stop_loss ?? undefined}
          takeProfits={analysis?.take_profits?.map(tp => ({ price: tp.price, level: tp.level })) ?? undefined}
        />
      )}
    </div>
  );
}
