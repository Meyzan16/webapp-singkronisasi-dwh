export interface SignalDef {
  id: number;
  icon: string;
  name: string;
  tag: string;
  tagColor: string;
  summary: string;
  formula: string;
  logic: string;
  example: string;
}

export const SIGNALS: SignalDef[] = [
  {
    id: 1, icon: "🔵", name: "Bollinger Band Squeeze",
    tag: "squeeze", tagColor: "bg-purple-600/20 text-purple-300 border-purple-600/30",
    summary: "Volatilitas menyempit — energi terkumpul sebelum ekspansi besar",
    formula: `BB Width = (Upper − Lower) / Middle
Upper  = SMA(n) + 2σ
Lower  = SMA(n) − 2σ
σ      = Std Dev close n-period

Trigger per style:
  Scalping   → BB Width < 3%  (BB period 14)
  Day Trade  → BB Width < 4.5% (BB period 20)
  Swing      → BB Width < 6%  (BB period 20)
  Position   → BB Width < 8%  (BB period 30)`,
    logic: "Bollinger Band menyempit = volatilitas rendah = market sedang coiling. Secara historis, squeeze selalu diikuti ekspansi besar ke salah satu arah. Scanner mendeteksi ini SEBELUM breakout.",
    example: "XAUUSDT BB Width 0.5% (Scalping) → squeeze sangat kuat → breakout imminent",
  },
  {
    id: 2, icon: "📦", name: "Volume Accumulation",
    tag: "accumulation", tagColor: "bg-teal-600/20 text-teal-300 border-teal-600/30",
    summary: "Smart money beli diam-diam — volume naik tapi harga belum bergerak",
    formula: `Vol Slope  = (Vol[-1] − Vol[-5]) / Vol[-5]
Price Slope = (Close[-1] − Close[-5]) / Close[-5]
Vol Ratio   = Vol[-1] / Avg(Vol[-21:-1])

Trigger per style (Vol Slope minimum):
  Scalping  → Vol Slope > 20% AND |Price Slope| < 4%
  Day Trade → Vol Slope > 25%
  Swing     → Vol Slope > 30%
  Position  → Vol Slope > 40%

Hidden Strength: Vol Slope > min AND Price Slope < 0`,
    logic: "Volume naik signifikan tapi harga flat/turun = institusi/whale akumulasi diam-diam. Ini sinyal paling powerful karena demand tersembunyi selalu mendahului kenaikan harga.",
    example: "ETHUSDT vol +52% dalam 5 candle, harga +0.3% → smart money masuk",
  },
  {
    id: 3, icon: "🎯", name: "Near Breakout Zone",
    tag: "breakout", tagColor: "bg-yellow-600/20 text-yellow-300 border-yellow-600/30",
    summary: "Harga mendekati resistance/support kritis — satu candle dari breakout",
    formula: `Lookback per style:
  Scalping  → 10 candle terakhir
  Day Trade → 15 candle terakhir
  Swing     → 20 candle terakhir
  Position  → 50 candle terakhir

Recent High = Max(High[-lookback:])
Recent Low  = Min(Low[-lookback:])

Dist to High = (RecentHigh − Price) / Price
Dist to Low  = (Price − RecentLow) / Price

Breakout pct per style:
  Scalping  → < 1.5%
  Day Trade → < 2.0%
  Swing/Pos → < 2.5%`,
    logic: "Harga mendekati high/low historis = tekanan beli/jual akan terkonsentrasi. Breakout dari zona ini biasanya dilanjutkan momentum besar.",
    example: "OPUSDT harga $0.1263, resistance $0.1265 (1.58%) → Scalping trigger",
  },
  {
    id: 4, icon: "📊", name: "RSI Coiling Zone",
    tag: "reversal", tagColor: "bg-blue-600/20 text-blue-300 border-blue-600/30",
    summary: "RSI di zona energi — belum overbought, momentum masih ada ruang",
    formula: `RSI(n) = 100 − (100 / (1 + RS))
RS = Avg Gain(n) / Avg Loss(n)

Period per style:
  Scalping  → RSI(9)  — lebih responsif, sinyal cepat
  Day Trade → RSI(14) — standar
  Swing     → RSI(14) — standar
  Position  → RSI(21) — lebih smooth, kurangi noise

Scoring:
  RSI < 30          → +15 × w_rsi  (oversold reversal)
  RSI 30–50         → +12 × w_rsi  (energy building)
  RSI 50–65         → +8  × w_rsi  (momentum building)
  RSI > 75          → −10 × w_rsi  (extended)

Weight w_rsi:
  Scalping×2.0 | DayTrade×1.5 | Swing×1.0 | Position×0.8`,
    logic: "RSI di zona 30-65 adalah sweet spot: tidak overbought (masih ada ruang), tidak oversold ekstrem. Scalping butuh RSI cepat (9) untuk menangkap momentum singkat. Position pakai RSI lambat (21) untuk filter noise.",
    example: "Scalping RSI(9)=28 → oversold → bouncing dalam 1-3 candle 15m berikutnya",
  },
  {
    id: 5, icon: "⚡", name: "EMA Compression",
    tag: "squeeze", tagColor: "bg-purple-600/20 text-purple-300 border-purple-600/30",
    summary: "EMA 9 dan 21 berkonvergensi — arah besar akan terjadi",
    formula: `EMA(n) = Price × k + EMA_prev × (1−k)
        k = 2 / (n+1)

EMA Spread = |EMA9 − EMA21| / Price

Compression threshold per style:
  Scalping  → Spread < 0.3%
  Day Trade → Spread < 0.5%
  Swing     → Spread < 0.8%
  Position  → Spread < 0.8%

Alignment bonus:
  EMA9 > EMA21 > EMA50 → +8 × w_ema (bullish)
  EMA9 < EMA21 < EMA50 → +8 × w_ema (bearish)

Weight w_ema:
  Scalping×1.2 | DayTrade×1.3 | Swing×1.0 | Position×1.5`,
    logic: "EMA 9/21 berkonvergensi = short-term dan mid-term trend seimbang. Kondisi ini selalu diikuti breakout. Position trading bobot EMA lebih tinggi karena trend makro lebih penting.",
    example: "Swing: EMA9=$0.1262, EMA21=$0.1264, spread=0.16% → compressed → breakout",
  },
  {
    id: 6, icon: "🟢", name: "Buy/Sell Pressure Shift",
    tag: "accumulation", tagColor: "bg-teal-600/20 text-teal-300 border-teal-600/30",
    summary: "Pergeseran tekanan beli/jual — momentum mulai berubah arah",
    formula: `Bull Vol % = Σ(Vol dimana Close ≥ Open) / Σ(Vol total)

n = min(5, len/2)  [window adaptif]

BP Recent = BullVol%(candle[-n:])
BP Prior  = BullVol%(candle[-2n:-n])
Shift     = BP Recent − BP Prior

Trigger:
  Shift > +15% → Buy pressure rising  (+15 × w_pressure)
  Shift < −15% → Sell pressure rising (+12 × w_pressure)

Weight w_pressure:
  Scalping×1.8 | DayTrade×1.5 | Swing×1.2 | Position×1.0`,
    logic: "Menganalisis apakah candle bullish punya lebih banyak volume dari candle bearish. Pergeseran buy pressure mendahului kenaikan harga. Scalping sangat sensitif terhadap perubahan ini (×1.8).",
    example: "BP Prior=38%, BP Recent=57%, shift=+19% → Scalping trigger → entry LONG",
  },
  {
    id: 7, icon: "🕯", name: "Candle Body Shrink",
    tag: "squeeze", tagColor: "bg-purple-600/20 text-purple-300 border-purple-600/30",
    summary: "Candle makin kecil = indecision = kompresi sebelum ekspansi",
    formula: `Body[i] = |Close[i] − Open[i]|

Body Slope = (Body[-1] − Body[-6]) / Body[-6]

Trigger: Body Slope < −50%

Diterapkan pada: Scalping, Day Trade, Swing
(Position TIDAK dipakai — noise terlalu tinggi di 1D)

Weight w_candle:
  Scalping×1.5 | DayTrade×1.2 | Swing×0.8 | Position×0.5`,
    logic: "Candle body mengecil = buyer dan seller seimbang = stalemate. Kondisi ini selalu berakhir breakout explosif. Untuk Position trading, candle 1D memiliki noise besar sehingga sinyal ini dinonaktifkan.",
    example: "Scalping 15m: bodies $0.008→$0.006→$0.004→$0.002 → −75% slope → coiling",
  },
];
