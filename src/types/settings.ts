export interface RiskSettings {
  positionSize: number; // % of balance
  stopLossPercent: number;
  takeProfitPercent: number;
  maxDrawdown: number;
  riskRewardMin: number; // Minimum R:R ratio
  leverage: number; // Futures leverage multiplier
  maxOpenPositions: number;
}

export interface TASettings {
  ema13Period: number;
  ema21Period: number;
  stochasticK: number;
  stochasticD: number;
  stochasticSmoothing: number;
  volumeMultiplier: number;
}

export interface APISettings {
  binanceApiKey: string;
  binanceApiSecret: string;
  testnetMode: boolean;
}

export interface AgentSettings {
  risk: RiskSettings;
  ta: TASettings;
  api: APISettings;
}
