"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RiskSettings } from "@/types/settings";

interface RiskConfigProps {
  settings: RiskSettings;
  onUpdate: (settings: RiskSettings) => void;
}

export function RiskConfig({ settings, onUpdate }: RiskConfigProps) {
  const handleChange = (key: keyof RiskSettings, value: number) => {
    onUpdate({ ...settings, [key]: value });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Risk Management</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div>
          <label className="text-sm font-semibold block mb-2">
            Position Size: {settings.positionSize}% of balance
          </label>
          <input
            type="range"
            min="0.1"
            max="10"
            step="0.1"
            value={settings.positionSize}
            onChange={(e) => handleChange("positionSize", parseFloat(e.target.value))}
            className="w-full"
          />
          <p className="text-xs text-muted-foreground mt-1">Risk per trade</p>
        </div>

        <div>
          <label className="text-sm font-semibold block mb-2">
            Stop Loss: {settings.stopLossPercent.toFixed(2)}%
          </label>
          <input
            type="range"
            min="0.5"
            max="5"
            step="0.1"
            value={settings.stopLossPercent}
            onChange={(e) => handleChange("stopLossPercent", parseFloat(e.target.value))}
            className="w-full"
          />
          <p className="text-xs text-muted-foreground mt-1">Distance from entry</p>
        </div>

        <div>
          <label className="text-sm font-semibold block mb-2">
            Take Profit: {settings.takeProfitPercent.toFixed(2)}%
          </label>
          <input
            type="range"
            min="0.5"
            max="20"
            step="0.1"
            value={settings.takeProfitPercent}
            onChange={(e) => handleChange("takeProfitPercent", parseFloat(e.target.value))}
            className="w-full"
          />
          <p className="text-xs text-muted-foreground mt-1">Profit target</p>
        </div>

        <div>
          <label className="text-sm font-semibold block mb-2">
            Max Drawdown: {settings.maxDrawdown.toFixed(2)}%
          </label>
          <input
            type="range"
            min="1"
            max="30"
            step="0.5"
            value={settings.maxDrawdown}
            onChange={(e) => handleChange("maxDrawdown", parseFloat(e.target.value))}
            className="w-full"
          />
          <p className="text-xs text-muted-foreground mt-1">Stop trading if exceeded</p>
        </div>

        <div>
          <label className="text-sm font-semibold block mb-2">
            Minimum Risk:Reward: 1:{settings.riskRewardMin.toFixed(1)}
          </label>
          <input
            type="range"
            min="1"
            max="5"
            step="0.1"
            value={settings.riskRewardMin}
            onChange={(e) => handleChange("riskRewardMin", parseFloat(e.target.value))}
            className="w-full"
          />
          <p className="text-xs text-muted-foreground mt-1">Filter signals below this ratio</p>
        </div>
      </CardContent>
    </Card>
  );
}
