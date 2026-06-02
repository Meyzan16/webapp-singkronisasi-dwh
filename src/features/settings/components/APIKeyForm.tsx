"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { APISettings } from "@/types/settings";

interface APIKeyFormProps {
  settings: APISettings;
  onUpdate: (settings: APISettings) => void;
}

export function APIKeyForm({ settings, onUpdate }: APIKeyFormProps) {
  const handleChange = (key: keyof APISettings, value: string | boolean) => {
    onUpdate({ ...settings, [key]: value });
  };

  const isMasked = (value: string) => value.length > 0 && !value.includes("sk_");
  const maskValue = (value: string) => value.substring(0, 10) + "..." + value.substring(value.length - 4);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Binance API Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
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
            . Enable "Spot Trading" permission only for security.
          </p>
        </div>

        <div>
          <label className="text-sm font-semibold block mb-2">
            API Key
            {settings.binanceApiKey && (
              <Badge className="ml-2 bg-green-500">Connected</Badge>
            )}
          </label>
          <input
            type="password"
            placeholder="sk_live_... (masked for security)"
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

        <div>
          <label className="text-sm font-semibold block mb-2">API Secret</label>
          <input
            type="password"
            placeholder="••••••••••••••••"
            value={settings.binanceApiSecret}
            onChange={(e) => handleChange("binanceApiSecret", e.target.value)}
            className="w-full p-2 border rounded-lg font-mono text-xs"
          />
        </div>

        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="testnet"
            checked={settings.testnetMode}
            onChange={(e) => handleChange("testnetMode", e.target.checked)}
            className="w-4 h-4"
          />
          <label htmlFor="testnet" className="text-sm font-semibold cursor-pointer">
            Use Testnet Mode
            <p className="text-xs text-muted-foreground font-normal mt-1">
              Test with fake money before live trading
            </p>
          </label>
        </div>

        <div className="bg-amber-50 border border-amber-200 p-3 rounded-lg">
          <p className="text-xs text-amber-900">
            <strong>Security:</strong> API keys are stored locally only. Never share your secret key.
            Restrict IP whitelist to your home/office IP on Binance.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
