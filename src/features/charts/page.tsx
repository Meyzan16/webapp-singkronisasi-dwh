"use client";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TimeframeSelector } from "./components";

const PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"];
const TIMEFRAMES = ["1w", "1d", "4h", "1h"];

export default function ChartsPage() {
  const [selectedPair, setSelectedPair] = useState(PAIRS[0]);
  const [selectedTF, setSelectedTF] = useState(TIMEFRAMES[1]);

  return (
    <div className="space-y-6">
      <Card className="bg-gradient-to-r from-primarygreen to-teal-500 text-white border-0">
        <CardContent className="pt-6">
          <h1 className="text-3xl font-bold mb-2">Technical Analysis Charts</h1>
          <p className="text-sm opacity-90">EMA crossovers, support/resistance zones, and trend visualization</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Chart Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-sm font-semibold block mb-2">Trading Pair</label>
            <select
              value={selectedPair}
              onChange={(e) => setSelectedPair(e.target.value)}
              className="w-full p-2 border rounded-lg"
            >
              {PAIRS.map((pair) => (
                <option key={pair} value={pair}>
                  {pair}
                </option>
              ))}
            </select>
          </div>
          <TimeframeSelector
            selectedTF={selectedTF}
            onSelect={setSelectedTF}
            timeframes={TIMEFRAMES}
          />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <div className="h-40 bg-neutral-50 rounded-lg flex items-center justify-center border border-neutral-200">
            <p className="text-muted-foreground">Chart Visualization Area</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
