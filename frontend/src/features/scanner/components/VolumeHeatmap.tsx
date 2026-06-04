import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface TokenSummary {
  pair: string;
  volume24h: number;
}

interface VolumeHeatmapProps {
  summary: TokenSummary[];
  loading: boolean;
}

export function VolumeHeatmap({ summary, loading }: VolumeHeatmapProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Volume Heatmap (24h)</CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="text-muted-foreground">Loading volume data...</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {summary.map((token) => {
              const maxVol = Math.max(...summary.map((t) => t.volume24h));
              const intensity = (token.volume24h / maxVol) * 100;
              return (
                <div key={token.pair} className="p-4 rounded-lg text-center" style={{backgroundColor: `rgba(20, 184, 166, ${intensity / 100})`}}>
                  <p className="font-bold text-sm">{token.pair}</p>
                  <p className="text-xs text-muted-foreground">{(token.volume24h / 1e6).toFixed(1)}M</p>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
