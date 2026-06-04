import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface Step {
  number: number;
  name: string;
  description: string;
  status: "completed" | "current" | "pending" | "future";
  layer?: string;
}

const getStatusBadge = (status: string) => {
  switch (status) {
    case "completed":
      return <Badge className="bg-green-500">✓ Done</Badge>;
    case "current":
      return <Badge className="bg-blue-500">● Current</Badge>;
    case "pending":
      return <Badge className="bg-yellow-500">⏳ Pending</Badge>;
    case "future":
      return <Badge className="bg-gray-500">⊘ Future</Badge>;
    default:
      return null;
  }
};

interface StepCardProps {
  step: Step;
}

export function StepCard({ step }: StepCardProps) {
  return (
    <Card
      className={`border-l-4 ${
        step.status === "completed"
          ? "border-l-green-500 bg-green-50"
          : step.status === "current"
            ? "border-l-blue-500 bg-blue-50"
            : step.status === "pending"
              ? "border-l-yellow-500 bg-yellow-50"
              : "border-l-gray-500 bg-gray-50"
      }`}
    >
      <CardContent className="pt-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-1">
              <span className="text-2xl font-bold text-muted-foreground w-8">
                {step.number}
              </span>
              <h3 className="text-lg font-semibold">{step.name}</h3>
              {step.layer && (
                <Badge variant="outline" className="text-xs">
                  {step.layer}
                </Badge>
              )}
            </div>
            <p className="text-sm text-muted-foreground ml-11">{step.description}</p>
          </div>
          <div className="flex-shrink-0">{getStatusBadge(step.status)}</div>
        </div>
      </CardContent>
    </Card>
  );
}
