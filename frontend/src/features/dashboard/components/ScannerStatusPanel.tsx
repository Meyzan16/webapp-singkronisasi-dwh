"use client";
import Link from "next/link";
import { fmtRelTime } from "@/lib/format";
import { SectionPanel } from "@/components/ui/section-panel";
import type { AgentState } from "@/types/health";

interface FuturesStatus {
  next_scan_in_min: number | null;
  agent1_results: number; agent2_results: number; agent3_results?: number;
  agent1_last_scan: number | null; agent2_last_scan: number | null; agent3_last_scan?: number | null;
}

function PulseNext({ min, color }: { min: number; color: string }) {
  return (
    <div className="flex items-center gap-1.5 text-[10px] text-neutral-500">
      <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${color}`} />
      Next scan: <strong className="text-neutral-700">{min.toFixed(1)} mnt</strong>
    </div>
  );
}

export function ScannerStatusPanel({ futStatus, futCount, oppCount, schedulerState }: {
  futStatus: FuturesStatus | null;
  futCount: number;
  oppCount: number;
  schedulerState?: AgentState;
}) {
  return (
    <SectionPanel title="📡 Scanner Status">
      <div className="p-4 space-y-4">
        {/* Futures scanner */}
        <div className="rounded-xl border border-neutral-200 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-black text-blue-600">⚡ FUTURES</span>
              <Link href="/scanner" className="text-[10px] text-neutral-400 hover:underline">buka →</Link>
            </div>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${futCount > 0 ? "bg-blue-100 text-blue-700" : "bg-neutral-100 text-neutral-500"}`}>
              {futCount < 0 ? "belum scan" : `${futCount} sinyal`}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            {[
              { label: "🎯 Pre-Gainer",    count: futStatus?.agent1_results ?? 0, ts: futStatus?.agent1_last_scan ?? null, color: "text-blue-600"   },
              { label: "📦 Accumulation",  count: futStatus?.agent2_results ?? 0, ts: futStatus?.agent2_last_scan ?? null, color: "text-purple-600" },
              { label: "🔥 Momentum",      count: futStatus?.agent3_results ?? 0, ts: futStatus?.agent3_last_scan ?? null, color: "text-orange-600" },
            ].map(a => (
              <div key={a.label}>
                <p className="text-neutral-400 text-[10px]">{a.label}</p>
                <p className={`font-bold ${a.color}`}>{a.count} sinyal</p>
                <p className="text-[10px] text-neutral-400">{fmtRelTime(a.ts)}</p>
              </div>
            ))}
          </div>
          {futStatus?.next_scan_in_min != null && <PulseNext min={futStatus.next_scan_in_min} color="bg-blue-400" />}
        </div>

        {/* Spot opportunity */}
        <div className="rounded-xl border border-neutral-200 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-black text-teal-600">🎯 SPOT OPP</span>
              <Link href="/opportunity" className="text-[10px] text-neutral-400 hover:underline">buka →</Link>
            </div>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${oppCount > 0 ? "bg-teal-100 text-teal-700" : "bg-neutral-100 text-neutral-500"}`}>
              {oppCount < 0 ? "belum scan" : `${oppCount} rekomendasi`}
            </span>
          </div>
          {schedulerState && (
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <p className="text-neutral-400 text-[10px]">Siklus Scan</p>
                <p className="font-bold text-teal-600">{schedulerState.cycle_count}x</p>
              </div>
              <div>
                <p className="text-neutral-400 text-[10px]">Interval</p>
                <p className="font-bold text-neutral-700">{schedulerState.interval_minutes}m</p>
              </div>
            </div>
          )}
          {schedulerState?.next_scan_in_min != null && <PulseNext min={schedulerState.next_scan_in_min} color="bg-teal-400" />}
        </div>
      </div>
    </SectionPanel>
  );
}
