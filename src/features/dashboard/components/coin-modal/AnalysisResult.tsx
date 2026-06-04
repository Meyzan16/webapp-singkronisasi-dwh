import { fmtPriceShort } from "@/lib/format";
import { STYLES } from "./types";
import type { Analysis } from "./types";

interface AnalysisResultProps {
  analysis: Analysis;
}

export function AnalysisResult({ analysis }: AnalysisResultProps) {
  const styleLabel = STYLES.find(s => s.key === analysis.style)?.label;
  const isLong     = analysis.direction === "LONG";
  const isShort    = analysis.direction === "SHORT";
  const hasSig     = !!analysis.direction;

  return (
    <div className={`rounded-2xl border-2 overflow-hidden ${
      isLong ? "border-green-400" : isShort ? "border-red-400" : "border-neutral-300"
    }`}>
      {/* Signal header */}
      <div className={`px-5 py-4 text-center ${
        isLong ? "bg-green-50" : isShort ? "bg-red-50" : "bg-neutral-50"
      }`}>
        <p className="text-xs uppercase tracking-wider text-muted-foreground font-semibold mb-1">
          {styleLabel} Signal
        </p>
        {hasSig ? (
          <>
            <p className={`text-4xl font-black ${isLong ? "text-green-600" : "text-red-500"}`}>
              {isLong ? "🟢 BUY" : "🔴 SELL"}
            </p>
            <p className="text-sm text-muted-foreground mt-1">
              Confidence: <strong>{analysis.confidence?.toFixed(0)}%</strong>
            </p>
          </>
        ) : (
          <>
            <p className="text-2xl font-black text-neutral-500">⏸ NO SIGNAL</p>
            <p className="text-xs text-orange-600 font-semibold mt-1 font-mono">{analysis.skip_reason}</p>
          </>
        )}
      </div>

      {/* No-signal explanation */}
      {!hasSig && analysis.stop_explanation && (
        <div className="bg-amber-50 border-t border-amber-200 px-5 py-4">
          <div className="flex gap-2 items-start">
            <span className="text-lg flex-shrink-0">💡</span>
            <div>
              <p className="text-xs font-bold text-amber-800 mb-1 uppercase tracking-wide">Kenapa berhenti di sini?</p>
              <p className="text-sm text-amber-900 leading-relaxed">{analysis.stop_explanation}</p>
            </div>
          </div>
        </div>
      )}

      {/* Trade levels */}
      {hasSig && (
        <div className="bg-white px-5 py-4 space-y-3">
          {/* Entry note */}
          {analysis.entry_note && (
            <div className={`rounded-xl px-3 py-2.5 text-xs leading-relaxed ${
              analysis.entry_type === "at_zone"
                ? "bg-green-50 border border-green-200 text-green-800"
                : analysis.entry_type === "wait_pullback" || analysis.entry_type === "wait_rally"
                ? "bg-amber-50 border border-amber-200 text-amber-800"
                : "bg-neutral-50 border text-neutral-600"
            }`}>
              {analysis.entry_note}
            </div>
          )}

          {/* Entry + SL */}
          <div className="grid grid-cols-2 gap-3">
            <div className={`rounded-xl p-3 border ${
              analysis.entry_type === "at_zone" ? "bg-green-50 border-green-300" : "bg-amber-50 border-amber-200"
            }`}>
              <p className="text-xs font-semibold text-neutral-600 mb-1">
                {analysis.entry_type === "at_zone" ? "✅ Entry Sekarang" : "⏳ Entry Ideal (Limit)"}
              </p>
              <p className="font-bold text-base">${fmtPriceShort(analysis.entry!)}</p>
              {analysis.entry_zone_low && analysis.entry_zone_high && (
                <p className="text-[10px] text-neutral-500 mt-0.5">
                  Zona: ${fmtPriceShort(analysis.entry_zone_low)} – ${fmtPriceShort(analysis.entry_zone_high)}
                </p>
              )}
            </div>

            <div className="bg-red-50 rounded-xl p-3 border border-red-200">
              <p className="text-xs font-semibold text-red-500">⛔ Stop Loss</p>
              <p className="font-bold text-base text-red-600">${fmtPriceShort(analysis.stop_loss!)}</p>
              {analysis.sl_basis && <p className="text-[10px] text-red-400 mt-0.5">{analysis.sl_basis}</p>}
            </div>
          </div>

          {/* Multi-TP */}
          {analysis.take_profits?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">Take Profit Targets</p>
              <div className="space-y-2">
                {analysis.take_profits.map(tp => (
                  <div key={tp.level} className="flex items-center justify-between bg-green-50 rounded-xl px-4 py-2.5 border border-green-200">
                    <div className="flex items-center gap-3">
                      <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white ${
                        tp.level === 1 ? "bg-green-400" : tp.level === 2 ? "bg-green-500" : "bg-green-600"
                      }`}>
                        T{tp.level}
                      </div>
                      <div>
                        <p className="font-bold text-green-700 text-sm">${fmtPriceShort(tp.price)}</p>
                        <p className="text-[10px] text-green-600">{tp.basis}</p>
                      </div>
                    </div>
                    <span className="text-xs font-bold text-primarygreen bg-white px-2 py-1 rounded-lg border border-primarygreen/30">
                      R:R {tp.rr}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
