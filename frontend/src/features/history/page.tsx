"use client";
import { useState } from "react";
import { OppSpotTab }   from "./components/OppSpotTab";
import { FuturesTab }   from "./components/FuturesTab";

type TabView = "opportunity" | "futures";

export default function HistoryPage() {
  const [activeTab, setActiveTab] = useState<TabView>("opportunity");

  return (
    <div className="space-y-6">

      {/* ── Tab switcher ────────────────────────────────────────────────────── */}
      <div className="flex gap-2">
        <button
          onClick={() => setActiveTab("opportunity")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all ${
            activeTab === "opportunity"
              ? "bg-teal-600 text-white shadow-sm"
              : "bg-white border border-neutral-200 text-neutral-600 hover:border-teal-300"
          }`}
        >
          <span>🎯</span> Spot — Opportunity
        </button>
        <button
          onClick={() => setActiveTab("futures")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all ${
            activeTab === "futures"
              ? "bg-gradient-to-r from-blue-600 to-purple-600 text-white shadow-sm"
              : "bg-white border border-neutral-200 text-neutral-600 hover:border-blue-300"
          }`}
        >
          <span>⚡</span> Futures — Agent 1+2
        </button>
      </div>

      {/* ── Opportunity SPOT tab ─────────────────────────────────────────────── */}
      {activeTab === "opportunity" && <OppSpotTab />}

      {/* ── Futures tab ──────────────────────────────────────────────────────── */}
      {activeTab === "futures" && <FuturesTab />}

    </div>
  );
}
