"use client";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"];
const TIMEFRAMES = ["1d", "4h", "1h"];

export default function BacktestPage() {
  const [selectedPair, setSelectedPair] = useState(TRADING_PAIRS[0]);
  const [selectedTF, setSelectedTF] = useState(TIMEFRAMES[0]);
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleRunBacktest = async () => {
    setLoading(true);
    try {
      const response = await fetch(`/api/v1/backtest/${selectedPair}/${selectedTF}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({pair: selectedPair, timeframe: selectedTF, start_date: startDate, end_date: endDate}),
      });
      if (!response.ok) throw new Error(`Backtest failed: ${response.statusText}`);
      const data = await response.json();
      setResults(data);
    } catch (err) {
      console.error("Backtest failed:", err);
      alert(`Error: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle>Backtest Configuration</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-semibold block mb-2">Trading Pair</label>
            <select value={selectedPair} onChange={(e) => setSelectedPair(e.target.value)} className="w-full p-2 border rounded-lg">
              {TRADING_PAIRS.map((pair) => (<option key={pair} value={pair}>{pair}</option>))}
            </select>
          </div>
          <div>
            <label className="text-sm font-semibold block mb-2">Timeframe</label>
            <div className="grid grid-cols-3 gap-2">
              {TIMEFRAMES.map((tf) => (
                <button key={tf} onClick={() => setSelectedTF(tf)} className={`p-2 rounded-lg text-sm ${selectedTF === tf ? "bg-primarygreen text-white" : "bg-neutral-100"}`}>
                  {tf.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-semibold block mb-2">Start Date</label>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full p-2 border rounded-lg" />
            </div>
            <div>
              <label className="text-sm font-semibold block mb-2">End Date</label>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-full p-2 border rounded-lg" />
            </div>
          </div>
          <button onClick={handleRunBacktest} disabled={loading} className="w-full p-3 bg-primarygreen text-white rounded-lg font-semibold disabled:opacity-50">
            {loading ? "Running backtest..." : "Run Backtest"}
          </button>
        </CardContent>
      </Card>
      {results && (
        <Card><CardContent className="pt-6"><p>Backtest results: {JSON.stringify(results).slice(0, 100)}...</p></CardContent></Card>
      )}
    </div>
  );
}
