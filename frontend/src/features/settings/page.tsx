"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { RiskConfig, TAParametersForm, APIKeyForm } from "./components";
import { AgentSettings } from "@/types/settings";

const DEFAULT_SETTINGS: AgentSettings = {
  risk: {
    positionSize: 2.0,
    stopLossPercent: 2.0,
    takeProfitPercent: 6.0,
    maxDrawdown: 10.0,
    riskRewardMin: 3.0,
    leverage: 5,
    maxOpenPositions: 3,
  },
  ta: {
    ema13Period: 13,
    ema21Period: 21,
    stochasticK: 5,
    stochasticD: 3,
    stochasticSmoothing: 3,
    volumeMultiplier: 1.5,
  },
  api: {
    binanceApiKey: "",
    binanceApiSecret: "",
    testnetMode: true,
  },
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<AgentSettings>(DEFAULT_SETTINGS);
  const [saved, setSaved] = useState(false);

  const handleSaveSettings = () => {
    localStorage.setItem("agentSettings", JSON.stringify(settings));
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <div className="space-y-6">
      <Card className="bg-gradient-to-r from-primarygreen to-teal-500 text-white border-0">
        <CardContent className="pt-6">
          <h1 className="text-3xl font-bold mb-2">Agent Settings</h1>
          <p className="text-sm opacity-90">
            Configure risk management, technical analysis parameters, and API credentials
          </p>
        </CardContent>
      </Card>

      <RiskConfig
        settings={settings.risk}
        onUpdate={(risk) => setSettings({ ...settings, risk })}
      />

      <TAParametersForm
        settings={settings.ta}
        onUpdate={(ta) => setSettings({ ...settings, ta })}
      />

      <APIKeyForm
        settings={settings.api}
        onUpdate={(api) => setSettings({ ...settings, api })}
      />

      <div className="flex gap-3">
        <button
          onClick={handleSaveSettings}
          className="flex-1 p-3 bg-primarygreen text-white rounded-lg font-semibold hover:bg-teal-600 transition-colors"
        >
          Save All Settings
        </button>
        <button
          onClick={() => setSettings(DEFAULT_SETTINGS)}
          className="flex-1 p-3 bg-neutral-200 text-black rounded-lg font-semibold hover:bg-neutral-300 transition-colors"
        >
          Reset to Defaults
        </button>
      </div>

      {saved && (
        <Card className="bg-green-50 border-green-200">
          <CardContent className="pt-6">
            <p className="text-sm text-green-800">✓ Settings saved successfully</p>
          </CardContent>
        </Card>
      )}

      <Card className="bg-neutral-50">
        <CardContent className="pt-6">
          <h3 className="font-semibold mb-2">Current Configuration Preview</h3>
          <pre className="text-xs overflow-auto bg-neutral-100 p-3 rounded max-h-64">
            {JSON.stringify(settings, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
