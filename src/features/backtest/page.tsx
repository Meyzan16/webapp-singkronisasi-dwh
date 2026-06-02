"use client";
import { useState } from "react";
import { ConfigPanel, ResultsDisplay } from "./components";

export default function BacktestPage() {
  const [selectedPair, setSelectedPair] = useState("BTCUSDT");
  const [selectedTF, setSelectedTF] = useState("1d");
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
        body: JSON.stringify({
          pair: selectedPair,
          timeframe: selectedTF,
          start_date: startDate,
          end_date: endDate,
        }),
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
      <ConfigPanel
        selectedPair={selectedPair}
        selectedTF={selectedTF}
        startDate={startDate}
        endDate={endDate}
        loading={loading}
        onPairChange={setSelectedPair}
        onTFChange={setSelectedTF}
        onStartDateChange={setStartDate}
        onEndDateChange={setEndDate}
        onRunBacktest={handleRunBacktest}
      />
      <ResultsDisplay results={results} />
    </div>
  );
}
