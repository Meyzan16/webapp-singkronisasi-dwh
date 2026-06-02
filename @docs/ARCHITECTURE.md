# Architecture — Crypto trading agent

## Overview

3 phases, 9 layers, waterfall gate system. Every tahap is an elimination filter — token yang gagal di satu tahap langsung di-skip.

```
Phase A (Discovery) → Phase B (Technical Analysis) → Phase C (Risk + Execution)
```

---

## Phase A — Discovery

### L1: Data ingestion

**Sources:**
- Binance REST API `/api/v3/klines` — OHLCV data for 5 pairs × 5 timeframes
- Binance REST API `/api/v3/ticker/24hr` — 24h volume, price change, txn count
- Binance WebSocket (later) — real-time kline updates

**Polling interval:** 30-60 seconds for ticker, klines updated per candle close.

**Data stored:** PostgreSQL table `klines`
```sql
CREATE TABLE klines (
    id SERIAL PRIMARY KEY,
    pair VARCHAR(20) NOT NULL,          -- e.g. 'BTCUSDT'
    timeframe VARCHAR(5) NOT NULL,      -- e.g. '1w', '1d', '4h', '1h', '15m'
    open_time BIGINT NOT NULL,          -- Unix timestamp ms
    open DECIMAL(20,8),
    high DECIMAL(20,8),
    low DECIMAL(20,8),
    close DECIMAL(20,8),
    volume DECIMAL(20,8),
    close_time BIGINT,
    taker_buy_volume DECIMAL(20,8),
    number_of_trades INTEGER,
    UNIQUE(pair, timeframe, open_time)
);
```

### L2: Signal detection (volume scanner)

Detects anomalies from raw data:
- **Volume spike**: `current_vol / avg_vol_7d > 2.0` = spike alert
- **Taker buy pressure**: `taker_buy_vol / total_vol > 0.6` = buying pressure
- **New listing flag**: new symbol appears in ticker that wasn't there before

---

## Phase B — Technical analysis (top-down, 5 tahap)

IMPORTANT: These run in strict sequence. Each is a gate — fail = skip token.

### T0: Wyckoff phase detection (1W + 1D)

Determines which market cycle phase each coin is in. This RESTRICTS what trades are allowed.

| Phase | Detection | Allowed action |
|-------|-----------|---------------|
| Accumulation | After downtrend, sideways range, low volume, spring/shakeout | LONG only |
| Mark up | HH + HL forming, volume confirms breakout | LONG on pullback |
| Distribution | After uptrend, sideways at top, volume divergence | NO new long. Prepare SHORT |
| Mark down | LH + LL forming, break below distribution range, volume confirms | SHORT on pullback |

Each coin can be in a DIFFERENT phase. BTC might be in markup while SUI is in accumulation.

### T1: Trend analysis (1W + 1D)

**Indicators:**
- EMA 13 and EMA 21
  - EMA13 > EMA21 → uptrend
  - EMA13 < EMA21 → downtrend
  - Fresh cross → trend shift signal
  - Distance widening → trend strengthening
- Trendline: minimum 2 touches to be valid. 3+ touches = strong. Break = trend invalid.

**Gate:** Trend must align with T0 Wyckoff phase. If not aligned → skip.

### T2: Area analysis (4H + 1D)

**Method:** Scan historical price data 30-100 days back. Find price levels where candles bounced (rejection wicks, body clusters).

**Rules:**
- S/R is a ZONE (±0.5-1% range), not an exact price
- More bounces = stronger area. 2 bounce = valid, 3+ = strong, 5+ = major
- Fibonacci 0.618 retracement as confluence area

**Validation:**
- Long + price at resistance → SKIP (not valid)
- Long + price at support → VALID
- Short + price at support → SKIP
- Short + price at resistance → VALID
- Counter-trend allowed ONLY if area has 4+ bounces (very strong area)

### T3: Pattern analysis (1H)

**Chart patterns detected:**
- Double bottom / double top
- Head & shoulders / inverse H&S
- Ascending/descending wedge
- Bull/bear flag
- Triangle (ascending, descending, symmetric)

**Market structure:**
- HH + HL = bullish bias
- LH + LL = bearish bias
- CHoCH (Change of Character) = bias shift
- BOS (Break of Structure) = confirmation

**Gate:** Pattern must confirm T0+T1 direction. If pattern contradicts → skip.

### T4: Trigger — entry and exit (15m + 1H)

Three confirmations needed for entry:

**1. Candlestick pattern:**
- BUY: Bullish engulfing, hammer/pin bar, morning star, rejection candle
- SELL: Bearish engulfing, shooting star, evening star

**2. Stochastic oscillator (5, 3, 3) — THE ONLY OSCILLATOR:**
- BUY: %K and %D both below 20 (oversold), then %K crosses ABOVE %D. Wait for candle close.
- SELL: %K and %D both above 80 (overbought), then %K crosses BELOW %D. Wait for candle close.
- No other oscillators (no RSI, no MACD). Stochastic 5,3,3 only.

**3. Volume confirmation:**
- Volume spike at trigger candle (above average)
- Taker buy > taker sell for long entry
- Dry volume (no volume) = NO ENTRY regardless of other signals

---

## Phase C — Risk + execution

### L5: Risk management

**Stop loss placement (pick the most logical):**
1. Below the strongest support area (most bounces)
2. Below liquidity cluster (where other SLs likely sit)
3. Below Fibonacci 0.618 level

**Non-negotiable rules:**
- Minimum Risk:Reward = 1:3. If SL→TP < 1:3 → SKIP trade
- Risk per trade: 1-2% of capital
- Position size = risk_amount / SL_distance
- Max daily loss: 3% of capital → agent stops generating signals

### L6: Signal card output

Every signal that passes ALL gates produces:
```json
{
  "pair": "SOL/USDT",
  "direction": "LONG",
  "phase": "Accumulation (spring)",
  "entry": 148.50,
  "stop_loss": 143.20,
  "take_profit": 164.40,
  "risk_reward": "1:3.0",
  "confidence": 87,
  "reasoning": {
    "T0": "Accumulation — spring detected below range",
    "T1": "EMA13 crossing above EMA21 on 1D",
    "T2": "Support at $145 — 4x bounce in 60 days",
    "T3": "Double bottom forming on 1H",
    "T4": "Bullish engulfing + Stoch cross up from 18 + vol spike 2.4x"
  },
  "timestamp": "2026-06-01T14:30:00Z"
}
```

### L7: Web dashboard (Next.js)

6 pages:
1. **Dashboard** — portfolio summary, active signals, Wyckoff phase per coin, PnL
2. **Scanner** — volume heatmap, top movers, new listings
3. **Signal feed** — live signal cards with entry/SL/TP, expandable TA reasoning
4. **Charts** — TradingView widget with EMA 13/21, Stoch 5,3,3, S/R overlay
5. **Backtest** — run strategy against historical data, equity curve, stats
6. **Settings** — agent config, TA params, risk rules, API keys

---

## Onchain layer (FUTURE — not for current phase)

DexScreener + GoPlus for token discovery and safety checks. Only relevant when expanding beyond 5 L1 pairs to low-cap/memecoin tokens. Not implemented now.