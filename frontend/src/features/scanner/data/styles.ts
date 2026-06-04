export interface StyleDef {
  key: string;
  icon: string;
  label: string;
  tf: string;
  duration: string;
  color: string;
  badge: string;
  params: [string, string][];
  weights: string;
  focus: string;
}

export const STYLE_CONFIGS: StyleDef[] = [
  {
    key: "scalping", icon: "⚡", label: "Scalping", tf: "15m", duration: "Menit–Jam",
    color: "from-yellow-500/20 to-orange-500/20 border-yellow-500/30",
    badge: "bg-yellow-600/20 text-yellow-300",
    params: [
      ["Timeframe",      "15m"],
      ["RSI Period",     "9 — responsif, sinyal cepat"],
      ["BB Period",      "14"],
      ["Lookback H/L",   "10 candle"],
      ["BB Squeeze",     "< 3% width"],
      ["Vol Slope Min",  "> 20%"],
      ["Pump Penalty",   "> 5% sudah naik"],
      ["Min SL jarak",   "≥ 0.8% dari entry"],
      ["Min R:R",        "≥ 1:3"],
      ["SL fallback",    "ATR × 1.0"],
      ["TP fallback",    "ATR × 3.5"],
      ["Min Score",      "25 pts"],
    ],
    weights: "RSI×2.0 · Pressure×1.8 · Breakout×1.5 · Candle×1.5",
    focus: "Momentum cepat, RSI ekstrem, volume spike. Entry di support terdekat (15m). SL minimal 0.8% — cukup ketat untuk scalp.",
  },
  {
    key: "daytrading", icon: "📅", label: "Day Trade", tf: "1H", duration: "Harian",
    color: "from-blue-500/20 to-indigo-500/20 border-blue-500/30",
    badge: "bg-blue-600/20 text-blue-300",
    params: [
      ["Timeframe",      "1H"],
      ["RSI Period",     "14 — standar"],
      ["BB Period",      "20"],
      ["Lookback H/L",   "15 candle"],
      ["BB Squeeze",     "< 4.5% width"],
      ["Vol Slope Min",  "> 25%"],
      ["Pump Penalty",   "> 8% sudah naik"],
      ["Min SL jarak",   "≥ 1.2% dari entry"],
      ["Min R:R",        "≥ 1:3"],
      ["SL fallback",    "ATR × 1.2"],
      ["TP fallback",    "ATR × 4.0"],
      ["Min Score",      "28 pts"],
    ],
    weights: "RSI×1.5 · Pressure×1.5 · Breakout×1.3 · EMA×1.3",
    focus: "Balance momentum + trend. Entry di support/resistance 1H. SL minimal 1.2% memberikan ruang noise intraday.",
  },
  {
    key: "swing", icon: "🌊", label: "Swing", tf: "4H", duration: "Hari–Minggu",
    color: "from-teal-500/20 to-green-500/20 border-teal-500/30",
    badge: "bg-teal-600/20 text-teal-300",
    params: [
      ["Timeframe",      "4H"],
      ["RSI Period",     "14"],
      ["BB Period",      "20"],
      ["Lookback H/L",   "20 candle (3.3 hari)"],
      ["BB Squeeze",     "< 6% width"],
      ["Vol Slope Min",  "> 30%"],
      ["Pump Penalty",   "> 12% sudah naik"],
      ["Min SL jarak",   "≥ 2.0% dari entry"],
      ["Min R:R",        "≥ 1:3"],
      ["SL fallback",    "ATR × 1.5"],
      ["TP fallback",    "ATR × 5.0"],
      ["Min Score",      "30 pts"],
    ],
    weights: "Accumulation×2.0 · Squeeze×1.8 · Breakout×1.5 · RSI×1.0",
    focus: "BB squeeze + akumulasi smart money. Entry di support zona 4H. SL minimal 2% mencegah stop-hunt harian.",
  },
  {
    key: "position", icon: "🏔", label: "Position", tf: "1D", duration: "Minggu–Bulan",
    color: "from-purple-500/20 to-violet-500/20 border-purple-500/30",
    badge: "bg-purple-600/20 text-purple-300",
    params: [
      ["Timeframe",      "1D"],
      ["RSI Period",     "21 — smooth, kurangi noise"],
      ["BB Period",      "30"],
      ["Lookback H/L",   "50 candle (~7 minggu)"],
      ["BB Squeeze",     "< 8% width"],
      ["Vol Slope Min",  "> 40%"],
      ["Pump Penalty",   "> 20% sudah naik"],
      ["Min SL jarak",   "≥ 3.0% dari entry"],
      ["Min R:R",        "≥ 1:3"],
      ["SL fallback",    "ATR × 2.0"],
      ["TP fallback",    "ATR × 7.0"],
      ["Min Score",      "35 pts"],
    ],
    weights: "Accumulation×2.5 · Squeeze×2.0 · EMA×1.5 · Breakout×1.8",
    focus: "Akumulasi panjang, trend makro, S/R weekly major. Entry di support zona 1D. SL 3% memberikan ruang volatilitas mingguan.",
  },
];
