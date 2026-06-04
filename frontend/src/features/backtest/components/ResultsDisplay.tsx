import { Card, CardContent } from "@/components/ui/card";

interface ResultsDisplayProps {
  results: unknown;
}

export function ResultsDisplay({ results }: ResultsDisplayProps) {
  if (!results) return null;

  return (
    <Card>
      <CardContent className="pt-6">
        <p>Backtest results: {JSON.stringify(results).slice(0, 100)}...</p>
      </CardContent>
    </Card>
  );
}
