"""
Opportunity Agent — multi-timeframe coin potential scanner.

Scans 100 USDT pairs looking for coins with HIGH POTENTIAL FOR PRICE INCREASE
regardless of trading style or timeframe.

Unlike the early breakout scanner (which generates style-specific entry/SL/TP),
this agent asks ONE question: "Which coins look INTERESTING right now?"

Signals used (multi-TF: 15m + 1h + 4h):
  - BB Squeeze across multiple timeframes
  - Smart money accumulation (volume ↑, price flat)
  - RSI reset from oversold zone
  - Buy pressure shift
  - Near key breakout level
  - Momentum building (higher lows, volume trend)
"""
