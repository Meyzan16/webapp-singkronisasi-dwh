"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { SignalsGrid } from "./SignalsGrid";
import { StyleConfigs } from "./StyleConfigs";
import { SLTPGuide } from "./SLTPGuide";

type DocTab = "styles" | "signals" | "sltp";

const TABS: { key: DocTab; label: string }[] = [
  { key: "styles",  label: "🎯 Config per Trading Style" },
  { key: "signals", label: "📐 7 Early-Warning Signals"  },
  { key: "sltp",    label: "📏 Rumus SL & TP"            },
];

export function ScannerDocs() {
  const [activeTab, setActiveTab] = useState<DocTab>("styles");
  const [showDocs, setShowDocs]   = useState(true);

  return (
    <div className="space-y-4">
      {/* Header card */}
      <Card className="bg-gradient-to-r from-neutral-900 to-neutral-800 text-white border-0">
        <CardContent className="pt-6 pb-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <span className="text-3xl">🔭</span>
                <h1 className="text-3xl font-bold">Early Breakout Scanner</h1>
              </div>
              <p className="text-sm opacity-70 max-w-2xl leading-relaxed">
                Deteksi koin yang <strong className="text-teal-300">akan naik/turun</strong> sebelum pergerakan besar terjadi.
                Setiap trading style memiliki <strong className="text-yellow-300">parameter, rumus, dan bobot sinyal berbeda</strong> yang disesuaikan dengan karakteristik timeframe-nya.
              </p>
            </div>
            <button
              onClick={() => setShowDocs(v => !v)}
              className="flex-shrink-0 text-xs bg-white/10 hover:bg-white/20 px-3 py-2 rounded-lg transition-colors">
              {showDocs ? "▲ Sembunyikan" : "▼ Lihat"} Arsitektur
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Docs body */}
      {showDocs && (
        <div className="space-y-4">
          {/* Tab switcher */}
          <div className="flex items-center gap-3">
            <div className="flex bg-white border rounded-xl p-1 gap-1 flex-wrap">
              {TABS.map(t => (
                <button key={t.key} onClick={() => setActiveTab(t.key)}
                  className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors ${
                    activeTab === t.key ? "bg-neutral-900 text-white" : "text-neutral-500 hover:text-black"
                  }`}>
                  {t.label}
                </button>
              ))}
            </div>
            <div className="flex-1 h-px bg-neutral-200" />
          </div>

          {activeTab === "styles"  && <StyleConfigs />}
          {activeTab === "signals" && <SignalsGrid />}
          {activeTab === "sltp"    && <SLTPGuide />}
        </div>
      )}
    </div>
  );
}
