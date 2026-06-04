import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function PipelineDiagram() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>TA Pipeline Waterfall</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>Signal generation follows strict waterfall with gating:</p>
        <div className="bg-neutral-50 p-3 rounded-lg font-mono text-xs space-y-1">
          <div>T0 (Wyckoff) ─┬─ GATE ─┐</div>
          <div>T1 (Trend)   ─┼─ GATE ─┼─ COMBINE</div>
          <div>T2 (S/R)     ─┼─ GATE ─┼─ COMBINE ─ FILTER</div>
          <div>T3 (Pattern) ─┼─ GATE ─┼─ COMBINE ─ (R:R &gt;= 1:3)</div>
          <div>T4 (Trigger) ─┴─ GATE ─┘</div>
        </div>
        <p className="mt-3">
          <strong>Timeframe Hierarchy:</strong> 1W (direction) → 1D (confirm) → 4H
          (zones) → 1H (pattern) → 15m (execute)
        </p>
      </CardContent>
    </Card>
  );
}
