"use client";
import { useState, type ReactNode } from "react";

// PLAN_v12 P6 — carousel ringkas untuk chart analitik: satu terlihat sekaligus,
// sisanya digeser (tab + dots + prev/next). Mengurangi over-informasi vertikal.
export interface CarouselSlide {
  key:   string;
  label: string;   // tab label (boleh pakai emoji)
  node:  ReactNode;
}

export function ChartCarousel({ slides }: { slides: CarouselSlide[] }) {
  const [idx, setIdx] = useState(0);
  const shown = slides.filter(Boolean);
  if (shown.length === 0) return null;
  if (shown.length === 1) return <>{shown[0].node}</>;   // 1 slide → tanpa kontrol

  const active = shown[Math.min(idx, shown.length - 1)];
  const go = (d: number) => setIdx(i => (i + d + shown.length) % shown.length);

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-3">
      {/* Tab bar */}
      <div className="flex items-center gap-1 mb-2 flex-wrap">
        {shown.map((s, i) => (
          <button key={s.key} onClick={() => setIdx(i)}
            className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-all ${
              i === Math.min(idx, shown.length - 1)
                ? "bg-teal-600 text-white"
                : "bg-neutral-100 text-neutral-500 hover:text-neutral-700"
            }`}>
            {s.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1">
          <button onClick={() => go(-1)} className="w-6 h-6 rounded-lg border border-neutral-200 text-neutral-500 hover:border-teal-400 text-xs">‹</button>
          <button onClick={() => go(1)}  className="w-6 h-6 rounded-lg border border-neutral-200 text-neutral-500 hover:border-teal-400 text-xs">›</button>
        </div>
      </div>

      {/* Slide */}
      <div>{active.node}</div>

      {/* Dots */}
      <div className="flex items-center justify-center gap-1.5 mt-2">
        {shown.map((s, i) => (
          <button key={s.key} onClick={() => setIdx(i)} aria-label={s.label}
            className={`h-1.5 rounded-full transition-all ${
              i === Math.min(idx, shown.length - 1) ? "w-4 bg-teal-500" : "w-1.5 bg-neutral-300"
            }`} />
        ))}
      </div>
    </div>
  );
}
