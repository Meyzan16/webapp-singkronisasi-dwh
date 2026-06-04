"use client";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { APISettings } from "@/types/settings";

interface TestResult {
  success: boolean;
  message: string;
  account_type?: string;
  can_trade?: boolean;
  spot_balance_usdt?: number;
}

interface APIKeyFormProps {
  settings: APISettings;
  onUpdate: (settings: APISettings) => void;
}

export function APIKeyForm({ settings, onUpdate }: APIKeyFormProps) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const handleChange = (key: keyof APISettings, value: string | boolean) => {
    onUpdate({ ...settings, [key]: value });
    // Clear test result when credentials change
    setTestResult(null);
  };

  const maskValue = (value: string) =>
    value.length > 14
      ? value.substring(0, 10) + "..." + value.substring(value.length - 4)
      : value.substring(0, 4) + "...";

  const handleTestConnection = async () => {
    if (!settings.binanceApiKey || !settings.binanceApiSecret) {
      setTestResult({
        success: false,
        message: "Please enter both API Key and Secret Key first.",
      });
      return;
    }

    setTesting(true);
    setTestResult(null);

    try {
      const res = await fetch("/api/v1/account/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: settings.binanceApiKey,
          api_secret: settings.binanceApiSecret,
          testnet: settings.testnetMode,
        }),
      });

      const data: TestResult = await res.json();

      if (!res.ok) {
        setTestResult({
          success: false,
          message: (data as { detail?: string }).detail ?? "Connection failed.",
        });
      } else {
        setTestResult(data);
      }
    } catch {
      setTestResult({
        success: false,
        message: "Network error — make sure backend is running.",
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Binance API Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Info note */}
        <div className="bg-blue-50 border border-blue-200 p-3 rounded-lg">
          <p className="text-xs text-blue-900">
            <strong>Note:</strong> Get API keys from{" "}
            <a
              href="https://www.binance.com/en/account/api-management"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-blue-700"
            >
              Binance Account Settings
            </a>
            . Enable Spot Trading and Futures permissions.
          </p>
        </div>

        {/* API Key */}
        <div>
          <label className="text-sm font-semibold block mb-2">
            API Key
            {settings.binanceApiKey && testResult?.success && (
              <Badge className="ml-2 bg-green-500">✓ Verified</Badge>
            )}
            {settings.binanceApiKey && !testResult && (
              <Badge className="ml-2 bg-neutral-400">Not tested</Badge>
            )}
          </label>
          <input
            type="password"
            placeholder="Enter your Binance API Key"
            value={settings.binanceApiKey}
            onChange={(e) => handleChange("binanceApiKey", e.target.value)}
            className="w-full p-2 border rounded-lg font-mono text-xs"
          />
          {settings.binanceApiKey && (
            <p className="text-xs text-muted-foreground mt-1">
              {maskValue(settings.binanceApiKey)}
            </p>
          )}
        </div>

        {/* API Secret */}
        <div>
          <label className="text-sm font-semibold block mb-2">API Secret</label>
          <input
            type="password"
            placeholder="Enter your Binance API Secret"
            value={settings.binanceApiSecret}
            onChange={(e) => handleChange("binanceApiSecret", e.target.value)}
            className="w-full p-2 border rounded-lg font-mono text-xs"
          />
        </div>

        {/* Testnet toggle */}
        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="testnet"
            checked={settings.testnetMode}
            onChange={(e) => handleChange("testnetMode", e.target.checked)}
            className="w-4 h-4 accent-primarygreen"
          />
          <label htmlFor="testnet" className="text-sm font-semibold cursor-pointer">
            Use Testnet Mode
            <p className="text-xs text-muted-foreground font-normal mt-1">
              Test with fake money before live trading
            </p>
          </label>
        </div>

        {/* Test Connection Button */}
        <button
          onClick={handleTestConnection}
          disabled={testing || !settings.binanceApiKey || !settings.binanceApiSecret}
          className="w-full p-3 rounded-lg font-semibold text-sm border-2 border-primarygreen text-primarygreen hover:bg-primarygreen hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {testing ? (
            <span className="flex items-center justify-center gap-2">
              <span className="animate-spin inline-block w-4 h-4 border-2 border-primarygreen border-t-transparent rounded-full" />
              Testing connection...
            </span>
          ) : (
            "🔌 Test Connection"
          )}
        </button>

        {/* Test Result Alert */}
        {testResult && (
          <div
            className={`p-4 rounded-lg border ${
              testResult.success
                ? "bg-green-50 border-green-300"
                : "bg-red-50 border-red-300"
            }`}
          >
            <div className="flex items-start gap-2">
              <span className="text-lg">{testResult.success ? "✅" : "❌"}</span>
              <div className="flex-1">
                <p
                  className={`text-sm font-semibold ${
                    testResult.success ? "text-green-800" : "text-red-800"
                  }`}
                >
                  {testResult.message}
                </p>
                {testResult.success && (
                  <div className="mt-2 space-y-1">
                    {testResult.account_type && (
                      <p className="text-xs text-green-700">
                        Account type:{" "}
                        <strong>{testResult.account_type}</strong>
                      </p>
                    )}
                    {testResult.can_trade !== undefined && (
                      <p className="text-xs text-green-700">
                        Trading enabled:{" "}
                        <strong>{testResult.can_trade ? "Yes ✓" : "No ✗"}</strong>
                      </p>
                    )}
                    {testResult.spot_balance_usdt !== undefined && (
                      <p className="text-xs text-green-700">
                        USDT Balance:{" "}
                        <strong>${testResult.spot_balance_usdt.toLocaleString()}</strong>
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Security note */}
        <div className="bg-amber-50 border border-amber-200 p-3 rounded-lg">
          <p className="text-xs text-amber-900">
            <strong>Security:</strong> API keys are stored locally only. Never
            share your secret key. Restrict IP whitelist to your home/office IP
            on Binance.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
