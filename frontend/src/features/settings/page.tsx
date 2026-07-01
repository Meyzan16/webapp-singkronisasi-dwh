"use client";
import { Card, CardContent } from "@/components/ui/card";
import { APIKeyForm, AgentOverviewCard, AgentConfigEditor, DBResetCard } from "./components";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <Card className="bg-gradient-to-r from-primarygreen to-teal-500 text-white border-0">
        <CardContent className="pt-6">
          <h1 className="text-3xl font-bold mb-2">Settings</h1>
          <p className="text-sm opacity-90">
            Konfigurasi Binance API credentials dan monitor sistem trading agent
          </p>
        </CardContent>
      </Card>

      <APIKeyForm />
      <AgentOverviewCard />
      <AgentConfigEditor />
      <DBResetCard />
    </div>
  );
}
