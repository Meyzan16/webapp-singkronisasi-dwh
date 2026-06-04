export interface ScanSignal {
  symbol: string;
  direction: string;
  probability: number;
  current_price: number;
  entry: number;
  entry_zone_low: number | null;
  entry_zone_high: number | null;
  entry_type: string;
  entry_note: string;
  change_24h: number;
  volume_ratio: number;
  signals: string[];
  key_level: number | null;
  stop_loss: number;
  take_profit: number;
  risk_reward: string;
  alert_type: string;
  sl_method: string;
  tp_method: string;
  style_note: string;
}

export interface ScannerData {
  results: ScanSignal[];
  scanned: number;
  style: string;
  style_label: string;
  timeframe: string;
  generated_at: number;
}
