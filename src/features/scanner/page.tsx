"use client";
import { Card, CardContent } from "@/components/ui/card";
import { ScannerWidget } from "@/features/dashboard/components/ScannerWidget";

export default function ScannerPage() {
  return (
    <div className="space-y-6">
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-3xl">🤖</span>
            <h1 className="text-3xl font-bold">24H Scanner Agent</h1>
          </div>
          <p className="text-sm opacity-75">
            Real-time scan across 598 USDT futures pairs · RSI · EMA alignment · Volume spike · Momentum breakout
          </p>
        </CardContent>
      </Card>

      <ScannerWidget fullPage />
    </div>
  );
}
