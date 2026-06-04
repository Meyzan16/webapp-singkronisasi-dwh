import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ConfigPanelProps {
  selectedPair: string;
  selectedTF: string;
  startDate: string;
  endDate: string;
  loading: boolean;
  onPairChange: (pair: string) => void;
  onTFChange: (tf: string) => void;
  onStartDateChange: (date: string) => void;
  onEndDateChange: (date: string) => void;
  onRunBacktest: () => Promise<void>;
}

const TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"];
const TIMEFRAMES = ["1d", "4h", "1h"];

export function ConfigPanel({
  selectedPair,
  selectedTF,
  startDate,
  endDate,
  loading,
  onPairChange,
  onTFChange,
  onStartDateChange,
  onEndDateChange,
  onRunBacktest,
}: ConfigPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Backtest Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <label className="text-sm font-semibold block mb-2">Trading Pair</label>
          <select
            value={selectedPair}
            onChange={(e) => onPairChange(e.target.value)}
            className="w-full p-2 border rounded-lg"
          >
            {TRADING_PAIRS.map((pair) => (
              <option key={pair} value={pair}>
                {pair}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-sm font-semibold block mb-2">Timeframe</label>
          <div className="grid grid-cols-3 gap-2">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => onTFChange(tf)}
                className={`p-2 rounded-lg text-sm ${
                  selectedTF === tf ? "bg-primarygreen text-white" : "bg-neutral-100"
                }`}
              >
                {tf.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-semibold block mb-2">Start Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => onStartDateChange(e.target.value)}
              className="w-full p-2 border rounded-lg"
            />
          </div>
          <div>
            <label className="text-sm font-semibold block mb-2">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => onEndDateChange(e.target.value)}
              className="w-full p-2 border rounded-lg"
            />
          </div>
        </div>
        <button
          onClick={onRunBacktest}
          disabled={loading}
          className="w-full p-3 bg-primarygreen text-white rounded-lg font-semibold disabled:opacity-50"
        >
          {loading ? "Running backtest..." : "Run Backtest"}
        </button>
      </CardContent>
    </Card>
  );
}
