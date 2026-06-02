import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function SystemStatusCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>System Status</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
          <span className="text-sm font-medium">Data Pipeline</span>
          <Badge className="bg-green-500">Online</Badge>
        </div>
        <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
          <span className="text-sm font-medium">TA Engine</span>
          <Badge className="bg-green-500">Running</Badge>
        </div>
        <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
          <span className="text-sm font-medium">Signal Generator</span>
          <Badge className="bg-green-500">Active</Badge>
        </div>
      </CardContent>
    </Card>
  );
}
