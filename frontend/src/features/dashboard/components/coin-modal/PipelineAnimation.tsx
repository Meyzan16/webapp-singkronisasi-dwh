import { Badge } from "@/components/ui/badge";
import { PIPELINE_STEPS } from "./types";
import type { Analysis, PipelineStatus } from "./types";

interface PipelineAnimationProps {
  pipelineStatus: PipelineStatus;
  visibleLayers: number;
  analysis: Analysis | null;
}

const layerBg = (status: string) =>
  status === "passed"      ? "bg-green-50 border-green-300 text-green-800"
  : status === "failed"    ? "bg-red-50 border-red-300 text-red-800"
  : status === "gate_failed" ? "bg-orange-50 border-orange-400 text-orange-800"
  : status === "blocked"   ? "bg-neutral-100 border-neutral-200 text-neutral-400 opacity-60"
  : "bg-neutral-50 border-neutral-200 text-neutral-600";

const layerIcon = (status: string) =>
  status === "passed"      ? "✓"
  : status === "failed"    ? "✗"
  : status === "gate_failed" ? "⛔"
  : status === "blocked"   ? "—"
  : "~";

export function PipelineAnimation({ pipelineStatus, visibleLayers, analysis }: PipelineAnimationProps) {
  const getLayer = (name: string) => analysis?.layers?.find(l => l.name === name);

  return (
    <div className="space-y-3">
      {/* Step bubbles */}
      <div className="flex items-center justify-between px-2">
        {PIPELINE_STEPS.map((step, i) => {
          const layer     = getLayer(step.name);
          const isVisible = i < visibleLayers;
          const isCurrent = i === visibleLayers && pipelineStatus === "running";
          const status    = layer?.status ?? (isCurrent ? "running" : "idle");
          const tf        = analysis?.timeframes?.[`t${i}`] ?? "";

          return (
            <div key={step.name} className="flex items-center gap-0">
              <div className={`flex flex-col items-center transition-all duration-500 ${isVisible ? "opacity-100" : "opacity-25"}`}>
                <div className={`w-11 h-11 rounded-full flex items-center justify-center text-lg border-2 transition-all duration-300 ${
                  isCurrent            ? "border-primarygreen bg-primarygreen/10 animate-pulse"
                  : status === "passed"      ? "border-green-500 bg-green-50"
                  : status === "failed"      ? "border-red-400 bg-red-50"
                  : status === "gate_failed" ? "border-orange-400 bg-orange-50"
                  : status === "blocked"     ? "border-neutral-200 bg-neutral-100 opacity-40"
                  : status === "skipped"     ? "border-neutral-300 bg-neutral-50"
                  : "border-neutral-200 bg-white"
                }`}>
                  {isCurrent             ? <span className="text-primarygreen animate-spin inline-block">⟳</span>
                    : status === "passed"      ? <span className="text-green-600 font-bold text-base">✓</span>
                    : status === "failed"      ? <span className="text-red-500 font-bold text-base">✗</span>
                    : status === "gate_failed" ? <span className="text-orange-500 font-bold text-base">⛔</span>
                    : status === "blocked"     ? <span className="text-neutral-400 text-base">—</span>
                    : <span>{step.icon}</span>}
                </div>
                <p className="text-xs font-bold mt-1">{step.layer}</p>
                {tf && <span className="text-[10px] bg-neutral-100 px-1.5 py-0.5 rounded font-mono text-neutral-500 mt-0.5">{tf.toUpperCase()}</span>}
                <p className="text-[10px] text-muted-foreground">{step.desc}</p>
              </div>
              {i < PIPELINE_STEPS.length - 1 && (
                <div className={`w-8 h-0.5 mx-1 mb-6 transition-all duration-500 ${
                  isVisible && i + 1 < visibleLayers ? "bg-primarygreen" : "bg-neutral-200"
                }`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Layer cards */}
      <div className="space-y-2">
        {PIPELINE_STEPS.map((step, i) => {
          const layer = getLayer(step.name);
          if (i >= visibleLayers || !layer) return null;
          return (
            <div key={step.name} className={`p-3 rounded-xl border flex items-start gap-3 ${layerBg(layer.status)}`}>
              <span className="font-bold w-5 text-center flex-shrink-0 text-sm">{layerIcon(layer.status)}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-sm">{layer.name}</span>
                  <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0">{layer.timeframe}</Badge>
                  {layer.signal && layer.signal !== "No chart pattern" && (
                    <Badge variant="outline" className="text-xs">{layer.signal}</Badge>
                  )}
                </div>
                {layer.detail && <p className="text-xs mt-0.5 opacity-80 leading-relaxed">{layer.detail}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
