"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface Settings {
  riskPerTrade: number;
  dailyLossCap: number;
  minRiskReward: number;
  enabledPairs: string[];
  enabledTimeframes: string[];
  minConfidence: number;
  autoTrade: boolean;
  slackNotifications: boolean;
  emailNotifications: boolean;
}

const TRADING_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "SUIUSDT"];
const TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"];

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({
    riskPerTrade: 1,
    dailyLossCap: 3,
    minRiskReward: 3.0,
    enabledPairs: TRADING_PAIRS,
    enabledTimeframes: TIMEFRAMES,
    minConfidence: 0.6,
    autoTrade: false,
    slackNotifications: true,
    emailNotifications: true,
  });

  const [saved, setSaved] = useState(false);

  const handleSaveSettings = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const handleTogglePair = (pair: string) => {
    setSettings((prev) => ({
      ...prev,
      enabledPairs: prev.enabledPairs.includes(pair)
        ? prev.enabledPairs.filter((p) => p !== pair)
        : [...prev.enabledPairs, pair],
    }));
  };

  const handleToggleTimeframe = (tf: string) => {
    setSettings((prev) => ({
      ...prev,
      enabledTimeframes: prev.enabledTimeframes.includes(tf)
        ? prev.enabledTimeframes.filter((t) => t !== tf)
        : [...prev.enabledTimeframes, tf],
    }));
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground mt-2">Agent configuration & risk rules</p>
      </div>

      {/* Risk Management */}
      <Card>
        <CardHeader>
          <CardTitle>Risk Management</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Risk Per Trade */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold">Risk Per Trade</label>
              <span className="text-sm font-bold text-primarygreen">{settings.riskPerTrade}%</span>
            </div>
            <input
              type="range"
              min="0.5"
              max="5"
              step="0.5"
              value={settings.riskPerTrade}
              onChange={(e) => setSettings((prev) => ({ ...prev, riskPerTrade: parseFloat(e.target.value) }))}
              className="w-full"
            />
            <p className="text-xs text-muted-foreground mt-2">Percentage of account to risk on each trade (0.5% - 5%)</p>
          </div>

          {/* Daily Loss Cap */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold">Daily Loss Cap</label>
              <span className="text-sm font-bold text-red-600">{settings.dailyLossCap}%</span>
            </div>
            <input
              type="range"
              min="1"
              max="10"
              step="0.5"
              value={settings.dailyLossCap}
              onChange={(e) => setSettings((prev) => ({ ...prev, dailyLossCap: parseFloat(e.target.value) }))}
              className="w-full"
            />
            <p className="text-xs text-muted-foreground mt-2">
              Stop trading when daily losses reach this % (1% - 10%)
            </p>
          </div>

          {/* Minimum Risk/Reward */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold">Minimum Risk/Reward Ratio</label>
              <span className="text-sm font-bold text-blue-600">1:{settings.minRiskReward.toFixed(1)}</span>
            </div>
            <input
              type="range"
              min="1"
              max="5"
              step="0.1"
              value={settings.minRiskReward}
              onChange={(e) => setSettings((prev) => ({ ...prev, minRiskReward: parseFloat(e.target.value) }))}
              className="w-full"
            />
            <p className="text-xs text-muted-foreground mt-2">Skip signals with R:R lower than this (1:1 - 1:5)</p>
          </div>

          {/* Minimum Confidence */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm font-semibold">Minimum Confidence</label>
              <span className="text-sm font-bold text-primarygreen">{(settings.minConfidence * 100).toFixed(0)}%</span>
            </div>
            <input
              type="range"
              min="0.4"
              max="0.95"
              step="0.05"
              value={settings.minConfidence}
              onChange={(e) => setSettings((prev) => ({ ...prev, minConfidence: parseFloat(e.target.value) }))}
              className="w-full"
            />
            <p className="text-xs text-muted-foreground mt-2">Only take signals above this confidence level (40% - 95%)</p>
          </div>
        </CardContent>
      </Card>

      {/* Trading Pairs */}
      <Card>
        <CardHeader>
          <CardTitle>Trading Pairs</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {TRADING_PAIRS.map((pair) => (
              <button
                key={pair}
                onClick={() => handleTogglePair(pair)}
                className={`p-3 rounded-lg border-2 transition-all ${
                  settings.enabledPairs.includes(pair)
                    ? "border-primarygreen bg-primarygreen/10"
                    : "border-neutral-300 bg-neutral-50"
                }`}
              >
                <p className="text-sm font-semibold">{pair}</p>
                {settings.enabledPairs.includes(pair) && <Badge className="mt-1 bg-primarygreen text-xs">Active</Badge>}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Timeframes */}
      <Card>
        <CardHeader>
          <CardTitle>Enabled Timeframes</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 md:grid-cols-5 gap-3">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => handleToggleTimeframe(tf)}
                className={`p-3 rounded-lg border-2 transition-all ${
                  settings.enabledTimeframes.includes(tf)
                    ? "border-primarygreen bg-primarygreen/10"
                    : "border-neutral-300 bg-neutral-50"
                }`}
              >
                <p className="text-sm font-semibold">{tf.toUpperCase()}</p>
                {settings.enabledTimeframes.includes(tf) && (
                  <Badge className="mt-1 bg-primarygreen text-xs">On</Badge>
                )}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Notifications */}
      <Card>
        <CardHeader>
          <CardTitle>Notifications</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Auto Trade */}
          <div className="flex items-center justify-between p-3 bg-neutral-50 rounded-lg">
            <div>
              <p className="font-semibold text-sm">Auto Trading</p>
              <p className="text-xs text-muted-foreground">Automatically execute signals (requires API key setup)</p>
            </div>
            <button
              onClick={() => setSettings((prev) => ({ ...prev, autoTrade: !prev.autoTrade }))}
              className={`px-4 py-2 rounded-lg text-sm font-semibold ${
                settings.autoTrade ? "bg-green-500 text-white" : "bg-neutral-300 text-neutral-700"
              }`}
            >
              {settings.autoTrade ? "ON" : "OFF"}
            </button>
          </div>

          {/* Slack Notifications */}
          <div className="flex items-center justify-between p-3 bg-neutral-50 rounded-lg">
            <div>
              <p className="font-semibold text-sm">Slack Notifications</p>
              <p className="text-xs text-muted-foreground">Send alerts to Slack channel</p>
            </div>
            <button
              onClick={() => setSettings((prev) => ({ ...prev, slackNotifications: !prev.slackNotifications }))}
              className={`px-4 py-2 rounded-lg text-sm font-semibold ${
                settings.slackNotifications ? "bg-blue-500 text-white" : "bg-neutral-300 text-neutral-700"
              }`}
            >
              {settings.slackNotifications ? "ON" : "OFF"}
            </button>
          </div>

          {/* Email Notifications */}
          <div className="flex items-center justify-between p-3 bg-neutral-50 rounded-lg">
            <div>
              <p className="font-semibold text-sm">Email Notifications</p>
              <p className="text-xs text-muted-foreground">Send alerts via email</p>
            </div>
            <button
              onClick={() => setSettings((prev) => ({ ...prev, emailNotifications: !prev.emailNotifications }))}
              className={`px-4 py-2 rounded-lg text-sm font-semibold ${
                settings.emailNotifications ? "bg-purple-500 text-white" : "bg-neutral-300 text-neutral-700"
              }`}
            >
              {settings.emailNotifications ? "ON" : "OFF"}
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Save Button */}
      <div className="flex gap-3">
        <button
          onClick={handleSaveSettings}
          className="flex-1 p-3 bg-primarygreen text-white rounded-lg font-semibold hover:opacity-90"
        >
          Save Settings
        </button>
        <button className="flex-1 p-3 bg-neutral-200 text-neutral-700 rounded-lg font-semibold hover:bg-neutral-300">
          Reset to Defaults
        </button>
      </div>

      {/* Success Message */}
      {saved && (
        <div className="p-4 bg-green-100 border border-green-500 rounded-lg">
          <p className="text-sm text-green-700 font-semibold">✓ Settings saved successfully</p>
        </div>
      )}

      {/* Information */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Settings Information</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>
            • <span className="font-semibold">Risk Per Trade:</span> How much of your account to risk on each trade
          </p>
          <p>
            • <span className="font-semibold">Daily Loss Cap:</span> Stop trading after this daily loss percentage
          </p>
          <p>
            • <span className="font-semibold">Risk/Reward:</span> Minimum acceptable ratio for entry (1:3 recommended)
          </p>
          <p>
            • <span className="font-semibold">Confidence:</span> Only take signals above this quality threshold
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
