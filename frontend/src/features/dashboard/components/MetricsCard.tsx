import { Card, CardContent } from "@/components/ui/card";

interface StatsData {
  totalSignals: number;
  activeSignals: number;
  buySignals: number;
  sellSignals: number;
  avgConfidence: number;
  avgRR: number;
}

interface MetricsCardProps {
  stats: StatsData;
}

export function MetricsCard({ stats }: MetricsCardProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground">Total Signals</p>
          <p className="text-3xl font-bold">{stats.totalSignals}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground">Active Signals</p>
          <p className="text-3xl font-bold text-primarygreen">{stats.activeSignals}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground">Avg Confidence</p>
          <p className="text-3xl font-bold">{(stats.avgConfidence * 100).toFixed(0)}%</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground">Buy Signals</p>
          <p className="text-3xl font-bold text-green-600">{stats.buySignals}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground">Sell Signals</p>
          <p className="text-3xl font-bold text-red-600">{stats.sellSignals}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-muted-foreground">Avg Risk/Reward</p>
          <p className="text-3xl font-bold">1:{stats.avgRR.toFixed(2)}</p>
        </CardContent>
      </Card>
    </div>
  );
}
