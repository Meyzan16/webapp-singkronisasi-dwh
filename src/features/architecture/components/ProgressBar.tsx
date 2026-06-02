import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ProgressBarProps {
  completed: number;
  total: number;
}

export function ProgressBar({ completed, total }: ProgressBarProps) {
  const progressPercent = (completed / total) * 100;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Implementation Progress</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-semibold">
            {completed} of {total} steps completed
          </span>
          <span className="text-2xl font-bold text-primarygreen">
            {progressPercent.toFixed(0)}%
          </span>
        </div>
        <div className="w-full bg-neutral-200 rounded-full h-3 overflow-hidden">
          <div
            className="bg-primarygreen h-full transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </CardContent>
    </Card>
  );
}
