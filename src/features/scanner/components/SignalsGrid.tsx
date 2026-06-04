"use client";
import { useState } from "react";
import { SIGNALS } from "../data/signals";

export function SignalsGrid() {
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
      {SIGNALS.map((sig) => (
        <div key={sig.id} className="bg-white border rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow">
          <button className="w-full text-left p-4 flex items-start gap-3"
            onClick={() => setExpanded(expanded === sig.id ? null : sig.id)}>
            <span className="text-2xl flex-shrink-0 mt-0.5">{sig.icon}</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <span className="font-bold text-sm">{sig.id}. {sig.name}</span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${sig.tagColor}`}>
                  {sig.tag}
                </span>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">{sig.summary}</p>
            </div>
            <span className="text-neutral-400 text-sm flex-shrink-0 mt-1">
              {expanded === sig.id ? "▲" : "▼"}
            </span>
          </button>

          {expanded === sig.id && (
            <div className="border-t bg-neutral-50 p-4 space-y-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-1.5">📐 Formula</p>
                <pre className="text-[11px] font-mono bg-neutral-900 text-green-400 p-3 rounded-lg overflow-x-auto leading-relaxed whitespace-pre-wrap">
                  {sig.formula}
                </pre>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-1.5">💡 Kenapa works?</p>
                <p className="text-xs text-neutral-700 leading-relaxed">{sig.logic}</p>
              </div>
              <div className="bg-teal-50 border border-teal-200 rounded-lg p-3">
                <p className="text-[10px] font-bold uppercase tracking-wider text-teal-600 mb-1">📌 Contoh Real</p>
                <p className="text-xs text-teal-800 font-mono">{sig.example}</p>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
