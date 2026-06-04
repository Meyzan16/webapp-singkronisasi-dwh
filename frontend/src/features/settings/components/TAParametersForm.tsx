"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TASettings } from "@/types/settings";

interface TAParametersFormProps {
  settings: TASettings;
  onUpdate: (settings: TASettings) => void;
}

export function TAParametersForm({ settings, onUpdate }: TAParametersFormProps) {
  const handleChange = (key: keyof TASettings, value: number) => {
    onUpdate({ ...settings, [key]: value });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Technical Analysis Parameters</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-semibold block mb-2">EMA 13 Period</label>
            <input
              type="number"
              min="5"
              max="50"
              value={settings.ema13Period}
              onChange={(e) => handleChange("ema13Period", parseInt(e.target.value))}
              className="w-full p-2 border rounded-lg"
            />
            <p className="text-xs text-muted-foreground mt-1">Fast EMA</p>
          </div>

          <div>
            <label className="text-sm font-semibold block mb-2">EMA 21 Period</label>
            <input
              type="number"
              min="5"
              max="50"
              value={settings.ema21Period}
              onChange={(e) => handleChange("ema21Period", parseInt(e.target.value))}
              className="w-full p-2 border rounded-lg"
            />
            <p className="text-xs text-muted-foreground mt-1">Slow EMA</p>
          </div>
        </div>

        <div>
          <label className="text-sm font-semibold block mb-2">
            Stochastic K Period: {settings.stochasticK}
          </label>
          <input
            type="range"
            min="3"
            max="20"
            step="1"
            value={settings.stochasticK}
            onChange={(e) => handleChange("stochasticK", parseInt(e.target.value))}
            className="w-full"
          />
        </div>

        <div>
          <label className="text-sm font-semibold block mb-2">
            Stochastic D Period: {settings.stochasticD}
          </label>
          <input
            type="range"
            min="1"
            max="10"
            step="1"
            value={settings.stochasticD}
            onChange={(e) => handleChange("stochasticD", parseInt(e.target.value))}
            className="w-full"
          />
        </div>

        <div>
          <label className="text-sm font-semibold block mb-2">
            Stochastic Smoothing: {settings.stochasticSmoothing}
          </label>
          <input
            type="range"
            min="1"
            max="10"
            step="1"
            value={settings.stochasticSmoothing}
            onChange={(e) => handleChange("stochasticSmoothing", parseInt(e.target.value))}
            className="w-full"
          />
        </div>

        <div>
          <label className="text-sm font-semibold block mb-2">
            Volume Multiplier: {settings.volumeMultiplier.toFixed(1)}x
          </label>
          <input
            type="range"
            min="0.5"
            max="3"
            step="0.1"
            value={settings.volumeMultiplier}
            onChange={(e) => handleChange("volumeMultiplier", parseFloat(e.target.value))}
            className="w-full"
          />
          <p className="text-xs text-muted-foreground mt-1">Volume confirmation threshold</p>
        </div>
      </CardContent>
    </Card>
  );
}
