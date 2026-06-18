// Shared types and helpers for spot-market feature

export interface SpotCoin {
  symbol:       string;
  base:         string;
  last_price:   number;
  price_change: number;
  change_pct:   number;
  high_24h:     number;
  low_24h:      number;
  volume_24h:   number;
  quote_vol_24h: number;
  trades_24h:   number;
}

export interface SpotMarketStats {
  total_pairs:     number;
  up_count:        number;
  down_count:      number;
  neutral_count:   number;
  avg_change_pct:  number;
  total_vol_usdt:  number;
  big_mover_count: number;
}

export interface SpotOverview {
  top_gainers:  SpotCoin[];
  top_losers:   SpotCoin[];
  top_volume:   SpotCoin[];
  big_movers:   SpotCoin[];
  market_stats: SpotMarketStats;
  generated_at: number;
}

export function fmtChangeColor(pct: number): string {
  if (pct >= 10)  return "text-green-600 font-black";
  if (pct >= 3)   return "text-green-500 font-bold";
  if (pct >= 0)   return "text-green-400";
  if (pct >= -3)  return "text-red-400";
  if (pct >= -10) return "text-red-500 font-bold";
  return "text-red-600 font-black";
}

export function fmtBg(pct: number): string {
  if (pct >= 15)  return "bg-green-600 text-white";
  if (pct >= 8)   return "bg-green-500 text-white";
  if (pct >= 3)   return "bg-green-400 text-white";
  if (pct >= 0)   return "bg-green-100 text-green-800";
  if (pct >= -3)  return "bg-red-100 text-red-700";
  if (pct >= -8)  return "bg-red-400 text-white";
  if (pct >= -15) return "bg-red-500 text-white";
  return "bg-red-700 text-white";
}
