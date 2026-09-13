// Architecture page — complete data from source code analysis (2026-06-30)
// All numbers verified against actual agent source files

// ─── SYSTEM OVERVIEW ──────────────────────────────────────────────────────────

export const SYSTEM_OVERVIEW = {
  spot: {
    scanInterval: "3 menit",
    monitorInterval: "60 detik",
    fastpassInterval: "30 detik (BigMover)",
    maxOpensCycle: 3,
    maxAge: "5–10 hari",
    minScore: 65,
    autoOpenScore: 85,
    minVolume: "$100K – $5M",
    minVolumeNote: "per-lane (lihat kartu lane)",
    rrMin: 3.5,
    executionCostPct: 0.2,
  },
  futures: {
    scanInterval: "2 menit",
    monitorInterval: "2 menit",
    fastMonitorInterval: "30 detik (semua posisi)",
    maxPositions: 6,
    maxPositionsNote: "global — satu dompet cross-margin, satu posisi per koin",
    maxHold: "8 jam (time-stop)",
    minScore: 65,
    autoOpenScore: "65 (= min score)",
    rrMin: 2.0,
    circuitBreakerPct: 15,
  },
};

// ─── SPOT: 4 LANES ────────────────────────────────────────────────────────────

export const SPOT_LANES = [
  {
    key: "accumulation",
    label: "Accumulation",
    emoji: "📦",
    color: "bg-blue-50 border-blue-200 text-blue-800",
    badgeColor: "bg-blue-100 text-blue-700",
    desc: "Setup utama — cari koin SEBELUM breakout terjadi via BB Squeeze, smart money accumulation, dan OI building.",
    trigger: "score ≥ 65, raw_score ≥ 85 untuk auto-open",
    minVolume: "$5,000,000",
    minScore: 65,
    autoScore: 85,
    slMethod: "Swing Low 4h/1h (last 20 candle) − 0.8% buffer",
    slRange: "1.5% – 5.0%",
    tp: ["Entry + risk × 2.5", "max(Entry + risk × 4.0, Entry × 1.06)", "max(Entry + risk × 7.0, Entry × 1.10)"],
    rrMin: 3.5,
    maxAge: "10 hari",
    tp1Partial: "30% posisi dijual di TP1 (ladder PLAN_v10)",
  },
  {
    key: "breakout",
    label: "Breakout Hunter",
    emoji: "💥",
    color: "bg-orange-50 border-orange-200 text-orange-800",
    badgeColor: "bg-orange-100 text-orange-700",
    desc: "Lane khusus volume spike ekstrem — masuk saat volume 5× rata-rata dalam 15m. Lebih agresif, SL berbasis ATR.",
    trigger: "vol_spike_15m ≥ 5×, change_24h ≥ 3%",
    minVolume: "$500,000",
    minScore: 60,
    autoScore: 75,
    slMethod: "Entry − ATR(14, 1h) × 1.5",
    slRange: "2.0% – 12.0%",
    tp: ["Entry + risk × 2.0", "Entry + risk × 3.5", "Entry + risk × 6.0"],
    rrMin: 3.0,
    maxAge: "6 jam (entry_mode momentum_entry)",
    tp1Partial: "30% posisi dijual di TP1 (ladder PLAN_v10)",
  },
  {
    key: "bigmover",
    label: "BigMover Chase",
    emoji: "🚀",
    color: "bg-amber-50 border-amber-200 text-amber-800",
    badgeColor: "bg-amber-100 text-amber-700",
    desc: "Wave Rider — masuk di tengah rally. Jika coin naik 2200%, agent bisa capture 1400% dengan masuk di gelombang.",
    trigger: "change_24h ≥ 10% ATAU change_7d ≥ 30%",
    minVolume: "$1,000,000",
    minScore: 55,
    autoScore: 65,
    slMethod: "Swing Low 15m (12 candle terakhir) − 1.5% buffer, max 5% dari entry",
    slRange: "1.0% – 5.5%",
    tp: [
      "Standard (< 50%): TP1 max(+5%, risk×1.5), lalu +12%, +25%",
      "Explosive (≥ 50%): TP1 max(+8%, risk×1.5), lalu +20%, +45%",
    ],
    rrMin: 2.0,
    maxAge: "3 hari",
    tp1Partial: "30% posisi dijual di TP1 (ladder PLAN_v10)",
    extras: [
      "B-Fix 2: TP1 adaptif minimal 1.5× risk — dulu +5% melawan lantai SL −5% (1:1)",
      "B-Fix 3: trailing struktur 4h aktif sejak TP1 (dulu hanya setelah TP2)",
      "Fastpass: rescan setiap 30 detik untuk coin ≥ 8% change_24h",
      "Drift tolerance: 3% (bukan 1% seperti lane lain) karena coin bergerak cepat",
      "RSI gate: >85 = skip; 80–85 OK jika change_1h ≥ 2% DAN 7d ≥ 30%",
      "Entry trap (G18): skip jika change_30m > 15% — sudah di puncak",
    ],
  },
  {
    key: "early_radar",
    label: "Early Radar",
    emoji: "🛰",
    color: "bg-rose-50 border-rose-200 text-rose-800",
    badgeColor: "bg-rose-100 text-rose-700",
    desc: "Micro-cap $100K–$1M yang tidak disentuh lane lain. Tangkap explosive move PALING AWAL: volume surge 2× (vs rata-rata 7 hari) + harga dekat 30d high.",
    trigger: "vol surge ≥ 2× (vs 7d avg) + harga ≤ 10% di bawah 30d high",
    minVolume: "$100K – $1M",
    minScore: 70,
    autoScore: 85,
    slMethod: "30d Low − 1% buffer (clamp 3%–10%)",
    slRange: "3.0% – 10.0%",
    tp: ["Entry + 10%", "Entry + 25%", "Entry + 60%"],
    rrMin: 4.0,
    maxAge: "10 hari",
    tp1Partial: "30% posisi dijual di TP1 (ladder PLAN_v10)",
    extras: [
      "⚠ Lane ini 0 trade seumur hidup — auto-open ≥85 dari skala maks 100 nyaris mustahil (lihat PLAN_SPOT_LANES S3)",
      "Universe $100K–$1M — blind spot lane lain (SYN-type coins mulai di sini)",
      "Risk ½ normal (0.5%/trade) — micro-cap lebih berisiko",
      "Max 2 posisi aktif sekaligus (cap ketat)",
      "Fetch klines HARIAN saja (murah, 1 TF bukan 3)",
      "Scoring: vol surge 40pts + near-high 30pts + momentum 15pts + RSI 10pts + BB 5pts",
      "Penalty −20pts jika Δ24h > 30% (sudah lari, terlambat)",
    ],
  },
];

// ─── SPOT: UNIVERSE FEEDERS (bukan lane) ─────────────────────────────────────
// PLAN_SPOT_LANES S1: keduanya hanya MENAMBAH koin ke pool kandidat, lalu koin itu
// dinilai oleh salah satu dari 4 lane di atas. Mereka tidak punya alert_type,
// entry_mode, maupun rumus SL/TP sendiri — jadi tidak akan pernah muncul sebagai
// lane tersendiri di History. Dulu "Weekly Momentum" tercantum sebagai lane ke-5
// lengkap dengan minScore/autoScore/rrMin yang tidak pernah dibaca kode mana pun.

export const SPOT_FEEDERS = [
  {
    key: "weekly",
    label: "Weekly Momentum (S4)",
    emoji: "📅",
    badgeColor: "bg-teal-100 text-teal-700",
    desc: "Menambah koin rank 100–250 by volume yang naik ≥20% dalam 7 hari. Koin yang sudah 'selesai moon' minggu ini lalu sepi tidak pernah masuk top-100 volume maupun supplement 24 jam.",
    trigger: "change_7d ≥ 20%, volume ≥ $1M, rank 100–250",
    cost: "Fetch klines 4h SAJA (1 TF, bukan 3) — murah",
    extras: [
      "Pool: 150 koin dari rank 100–250, maksimal 15 tambahan per cycle",
      "Hasilnya dinilai lane Accumulation / BigMover — dicatat atas nama lane itu",
    ],
  },
  {
    key: "momentum_24h",
    label: "Momentum 24h (R7)",
    emoji: "⚡",
    badgeColor: "bg-amber-100 text-amber-700",
    desc: "Menambah koin di luar top-100 volume yang sedang bergerak ≥5% dalam 24 jam — volume normalnya kecil tapi melonjak saat pump.",
    trigger: "change_24h ≥ 5%, di luar top-100 volume",
    cost: "Ikut fetch 3 TF bersama kandidat utama",
    extras: ["Maksimal 20 koin tambahan per cycle"],
  },
];

// ─── SPOT: 12 SCORING SIGNALS ────────────────────────────────────────────────

export const SPOT_SIGNALS = [
  {
    id: 1,
    name: "BB Squeeze Multi-TF",
    emoji: "🔵",
    maxPts: 35,
    category: "setup",
    formula: "BB_width = (upper − lower) / middle\nSqueeze jika width < threshold per TF:\n  15m: 3.5% | 1h: 5.0% | 4h: 7.0%",
    scoring: [
      { cond: "≥ 2 TF squeeze + direction gate",  pts: 35 },
      { cond: "1 TF squeeze saja",                 pts: 10 },
      { cond: "Tanpa direction gate (downgrade)",   pts: 10, note: "auto-open diblokir" },
    ],
    why: "Volatilitas menyempit (BB menguncup) = energi terkompresi sebelum breakout besar. Makin sempit, makin besar potensi ledakan.",
  },
  {
    id: 2,
    name: "Smart Money Accumulation",
    emoji: "📦",
    maxPts: 25,
    category: "setup",
    formula: "vol_slope  = (vol[-1] − vol[-5]) / vol[-5]\nprice_slope = (close[-1] − close[-5]) / close[-5]",
    scoring: [
      { cond: "vol_slope > 0.25 AND |price_slope| < 3%",       pts: 25, note: "paling kuat" },
      { cond: "vol_ratio > 2.0 AND |price_slope| < 4%",        pts: 15 },
      { cond: "vol_slope > 0.15 AND price_slope < 0 (turun)",  pts: 20, note: "hidden strength" },
    ],
    why: "Volume naik tapi harga flat = institutional buying diam-diam. Mereka tidak mau memompa harga sebelum posisi penuh.",
  },
  {
    id: 3,
    name: "Volume Z-Score",
    emoji: "📊",
    maxPts: 10,
    category: "setup",
    formula: "vol_z = (current_vol − mean_200) / stdev_200\nvs baseline 200 candle 1h",
    scoring: [
      { cond: "vol_z ≥ 2.5", pts: 10, note: "sangat abnormal" },
      { cond: "vol_z ≥ 1.5", pts: 5  },
    ],
    why: "Volume yang sangat melebihi baseline historis (2.5 sigma) adalah tanda aktivitas yang bukan random.",
  },
  {
    id: 4,
    name: "RSI Sweet Spot",
    emoji: "📈",
    maxPts: 12,
    category: "timing",
    formula: "RSI(14) atau RSI(4) untuk timeframe lebih pendek",
    scoring: [
      { cond: "RSI 40–55 (momentum turning)", pts: 8 },
      { cond: "RSI 35–43 (recovering)",       pts: 5 },
      { cond: "RSI 55–63 (building)",         pts: 3 },
    ],
    penalties: [
      { cond: "RSI(4h) > 82 (bukan strong weekly)", pts: -99, note: "AUTO-SKIP" },
      { cond: "RSI > 75 AND bukan strong weekly",   pts: -15 },
      { cond: "RSI > 75 AND strong weekly",         pts: -5  },
      { cond: "RSI > 72",                           pts: -10 },
      { cond: "RSI > 65",                           pts: -5  },
    ],
    why: "RSI 40–55 = momentum sedang bangun, belum terlambat. RSI > 75 = overbought, entry terlambat.",
  },
  {
    id: 5,
    name: "Funding Rate",
    emoji: "💸",
    maxPts: 15,
    category: "market",
    formula: "Dari Binance Futures funding rate per 8 jam",
    scoring: [
      { cond: "fr < −0.04%", pts: 15, note: "short squeeze fuel" },
      { cond: "fr < −0.01%", pts: 10 },
      { cond: "fr ≤ 0.01%",  pts: 6,  note: "neutral, healthy" },
    ],
    penalties: [
      { cond: "fr > 0.05%", pts: -8, note: "longs overcrowded" },
      { cond: "fr > 0.03%", pts: -4 },
    ],
    why: "Funding negatif = shorts overcrowded, siap di-squeeze. Funding tinggi = longs berlebihan, reversal risk.",
  },
  {
    id: 6,
    name: "Open Interest Building",
    emoji: "🏗",
    maxPts: 18,
    category: "market",
    formula: "oi_chg = (oi_now − oi_prev) / oi_prev × 100\noi_chg_prev = perubahan OI periode sebelumnya",
    scoring: [
      { cond: "oi_chg ≥ 3.0%", pts: 12, note: "institutional build-up" },
      { cond: "oi_chg ≥ 1.5%", pts: 8  },
      { cond: "oi_chg ≥ 0.5%", pts: 4  },
      { cond: "OI Acceleration: oi_chg > oi_chg_prev > 0", pts: 6, note: "bonus akselerasi" },
    ],
    penalties: [
      { cond: "oi_chg < −2.0%", pts: -5, note: "posisi ditutup massal" },
    ],
    why: "OI naik = posisi baru dibuka (konviksi). OI akselerasi = institutional buying yang semakin agresif.",
  },
  {
    id: 7,
    name: "Near Resistance / Breakout",
    emoji: "🎯",
    maxPts: 15,
    category: "setup",
    formula: "dist_to_resistance = (resistance − price) / price × 100",
    scoring: [
      { cond: "dist < 3% dari resistance",              pts: 10 },
      { cond: "Fresh breakout: price > recent_high × 0.99 AND change_24h 0–2%", pts: 5, note: "baru breakout, belum mahal" },
    ],
    penalties: [
      { cond: "−0.5% sd 0% dari ATH",    pts: -10, note: "sangat late entry" },
      { cond: "−2% sd −0.5% dari ATH",   pts: -5  },
    ],
    why: "Dekat resistance = titik keputusan kritis. Fresh breakout = momentum baru, belum banyak yang masuk.",
  },
  {
    id: 8,
    name: "EMA Alignment",
    emoji: "⚡",
    maxPts: 15,
    category: "trend",
    formula: "EMA9, EMA21 dihitung di setiap timeframe (15m, 1h, 4h)",
    scoring: [
      { cond: "EMA9 > EMA21 di ≥ 2 TF", pts: 10 },
      { cond: "Ketiga TF bullish",        pts: 5,  note: "bonus full align" },
    ],
    why: "EMA9 > EMA21 = trend bullish jangka pendek. Makin banyak TF yang align, makin kuat trennya.",
  },
  {
    id: 9,
    name: "Buy Pressure Shift",
    emoji: "🟢",
    maxPts: 15,
    category: "momentum",
    formula: "taker_ratio = taker_buy_vol / total_vol (rata-rata 15 candle)\nshift = taker_now − taker_prev",
    scoring: [
      { cond: "shift > 0.20", pts: 15, note: "dominasi buyer tiba-tiba" },
      { cond: "shift > 0.10", pts: 8  },
    ],
    why: "Pergeseran tiba-tiba ke dominasi taker buy = institutional market order. Sinyal konviksi kuat.",
  },
  {
    id: 10,
    name: "Volume Spike",
    emoji: "📈",
    maxPts: 10,
    category: "momentum",
    formula: "vol_ratio = current_vol / avg_vol (rata-rata historis)",
    scoring: [
      { cond: "vol_ratio ≥ 5.0×", pts: 10, note: "anomali besar" },
      { cond: "vol_ratio ≥ 3.0×", pts: 5  },
    ],
    why: "Volume spike 5× = ada event besar. Coupled dengan harga, ini sinyal momentum yang tidak bisa diabaikan.",
  },
  {
    id: 11,
    name: "Momentum Context",
    emoji: "🚀",
    maxPts: 20,
    category: "momentum",
    formula: "change_24h dari Binance ticker\nchange_7d dari 4h klines",
    scoring: [
      { cond: "change_24h 3–20%",  pts: 8, note: "healthy momentum" },
      { cond: "change_7d ≥ 50%",   pts: 8, note: "weekly bonus" },
      { cond: "change_7d ≥ 30%",   pts: 5, note: "weekly bonus" },
    ],
    penalties: [
      { cond: "change_24h > 15% AND change_1h < −2%",  pts: -5,  note: "pullback saat sudah tinggi" },
      { cond: "change_24h > 15% AND change_1h ≥ −2%",  pts: -25, note: "sedang chasing" },
      { cond: "change_24h 8–15% AND change_1h < −1%",  pts: -6  },
      { cond: "change_24h 8–15%",                       pts: -12 },
      { cond: "change_24h < −15%",                      pts: -10, note: "dumping" },
    ],
    why: "Momentum 3–20% = sweet spot, masih ada room. Di atas 15% dengan 1h masih naik = terlambat masuk.",
  },
  {
    id: 12,
    name: "Momentum Chase (R8)",
    emoji: "🔥",
    maxPts: 23,
    category: "momentum",
    formula: "Khusus coin change_24h ≥ 10% ATAU change_7d ≥ 20%\n(weekly strong momentum)",
    scoring: [
      { cond: "RSI 40–65 AND EMA9 > EMA21 × 0.99", pts: 15 },
      { cond: "Volume menurun saat pullback",        pts: 8, note: "healthy retracement" },
    ],
    why: "Kalau coin sudah bergerak kuat, konfirmasi RSI tidak overbought + volume pullback sehat = re-entry valid.",
  },
];

// ─── SPOT: DIRECTION GATE ─────────────────────────────────────────────────────

export const SPOT_DIRECTION_GATE = {
  desc: "Gate wajib sebelum auto-open. Tanpa konfirmasi ini, BB Squeeze hanya 10 pts (bukan 35) dan auto-open diblokir paksa.",
  conditions: [
    "taker_ratio ≥ 0.55 (55% buyer agresif dalam 15 candle terakhir)",
    "ATAU EMA9 > EMA21 pada timeframe 1h",
  ],
};

// ─── SPOT: MONITOR LAYERS ────────────────────────────────────────────────────

export const SPOT_MONITOR_LAYERS = [
  {
    layer: "L0",
    title: "Wick Detection",
    emoji: "🕯",
    color: "bg-neutral-100 border-neutral-300",
    desc: "Fetch 1m klines untuk deteksi wick yang menyentuh level DI ANTARA poll 60 detik. Mencegah miss TP/SL karena polling interval.",
    closes: [
      { reason: "TP dan SL keduanya tersentuh di window yang sama → SL wins (konservatif)" },
    ],
  },
  {
    layer: "L1",
    title: "Dynamic Profit Ladder (PLAN_v10)",
    emoji: "🪜",
    color: "bg-red-50 border-red-200",
    desc: "Scale-out bertingkat + runner. Tiap rung bank profit (permanen), floor ratchet naik, sisanya ride sampai TP-n. Tak ada cap di TP2 lagi.",
    closes: [
      { reason: "TP1 hit", status: "partial", note: "jual 30%, floor → entry + 50%×(TP1−entry)" },
      { reason: "TP2 hit", status: "partial", note: "jual 20% (dulu close 100%), floor → ≥TP1, konversi jadi runner" },
      { reason: "TP3 hit", status: "partial", note: "jual 15%, mode runner trailing" },
      { reason: "TP4…TP-n dinamis", status: "partial", note: "jual 5%/rung tiap +1×ATR(1h) selama gate (taker≥0.5, vol≥1.2, score≥50) hijau; runner min 15%" },
      { reason: "Runner exit", status: "tp", note: "struktur 4h patah (EMA9<EMA21) → jual sisa; reason=trend_structure_broken" },
      { reason: "SL hit",  status: "sl", note: "close sisa; jika TP1 pernah hit → reason=tp1_breakeven (bukan rugi)" },
    ],
  },
  {
    layer: "L2",
    title: "Risk-Adjusted Exits",
    emoji: "⚠️",
    color: "bg-yellow-50 border-yellow-200",
    desc: "Hanya aktif SETELAH 30 menit hold (MIN_HOLD_MINUTES). Mencegah exit prematur karena noise.",
    closes: [
      { reason: "trend_reversal: EMA9 < EMA21×0.998 DAN entry_ema_bullish=True", note: "no profit floor" },
      { reason: "profit_protection: RSI > 80 AND pnl ≥ 50% jalan ke TP2 AND range < 0.5% (stagnan)" },
      { reason: "flow_reversal: taker_ratio < 0.38 AND pnl ≥ 50% jalan ke TP2" },
      { reason: "risk_adjusted: RSI > 75 AND pnl_gross < −2% (loss-cutting, setup gagal)" },
    ],
  },
  {
    layer: "L2.5",
    title: "Stagnant / Urgent Rotation",
    emoji: "🔄",
    color: "bg-blue-50 border-blue-200",
    desc: "Tukar posisi stagnan dengan kandidat yang lebih baik. Dua reason: stagnant_rotation (normal) & urgent_rotation.",
    closes: [
      { reason: "🔁 stagnant_rotation (hari 2+): harga ±3% dari entry, kandidat outscore ≥10 pts DAN kandidat ≥ 85 pts" },
      { reason: "🔄 urgent_rotation (hari 1+): kandidat outscore ≥25 pts DAN kandidat ≥ 90 pts (apa pun drift)" },
      { reason: "Guard staleness: rotasi di-skip jika scan cache > 10 menit", note: "cegah tukar posisi berdasar kandidat basi (PLAN_v8 P4)" },
    ],
  },
  {
    layer: "L3",
    title: "Profit Lock Absolute",
    emoji: "🔒",
    color: "bg-green-50 border-green-200",
    desc: "Berjalan di SETIAP check cycle. Lock profit jika harga turun dari peak. PLAN_v10: tier tinggi untuk pump besar — 1000% tak boleh menguap.",
    closes: [
      { reason: "peak_pnl ≥ 300% AND current_pnl < peak × 0.90 → LOCK", note: "beri balik maks 10% dari peak" },
      { reason: "peak_pnl ≥ 100% AND current_pnl < peak × 0.85 → LOCK", note: "beri balik maks 15%" },
      { reason: "peak_pnl ≥ 40% AND current_pnl < peak × 0.75 → LOCK", note: "beri balik maks 25%" },
      { reason: "peak_pnl ≥ 25% AND current_pnl < peak × 0.70 → LOCK", note: "beri balik maks 30%" },
      { reason: "peak_pnl ≥ 15% AND current_pnl < peak × 0.60 → LOCK", note: "beri balik maks 40%" },
    ],
  },
  {
    layer: "L4",
    title: "Max Age Expiry",
    emoji: "⏰",
    color: "bg-neutral-50 border-neutral-200",
    desc: "Posisi yang terlalu lama ditutup otomatis untuk bebaskan modal.",
    closes: [
      { reason: "fresh_setup (accumulation): max 10 hari → close di market, reason=max_age_expired" },
      { reason: "momentum_chase (bigmover, breakout): max 5 hari → close di market" },
    ],
  },
];

// ─── FUTURES: 4 AGENTS ───────────────────────────────────────────────────────

export const FUTURES_AGENTS = [
  {
    key: "agentic",
    label: "Agen Tunggal",
    style: "futures_agentic",
    emoji: "🧠",
    color: "from-teal-500/10 to-emerald-500/10 border-teal-300",
    badgeColor: "bg-teal-100 text-teal-700",
    file: "agents/futures/agentic.py",
    philosophy: "Satu lane, satu skor, satu ambang. Menggantikan empat pemindai lama (2.764 baris) — dari 112 trade era lama, 81% datang dari satu lane. Tesisnya MOMENTUM: koin yang sudah bergerak, dikonfirmasi 1h, volume, OI, dan funding yang belum sesak.",
    direction: "LONG + SHORT (arah = tanda Δ24h)",
    leverageMax: 6,
    laneKey: "agentic",
    minScore: 65,
    slMethod: "ATR(14) × exit_sl_atr_mult (1,2)",
    slCap: "TP1 1,2 ATR · TP2 2,5 ATR · sisa 25% pelari",
    maxMarginLoss: "risiko 1% modal per posisi (size_risk_base_pct)",
    signals: [
      { name: "Besaran gerak Δ24h",       maxPts: 30, detail: "5–10%: 15 (momentum_awal) | 10–20%: 25 (mapan) | 20–50%: 30 (kuat) | 50–150%: 18 (ekstrem, size ½)" },
      { name: "Konfirmasi arah 1h",       maxPts: 18, detail: "searah: 18 | datar (zona re-entry): 10 | berlawanan: 3" },
      { name: "Volume konfirmasi",        maxPts: 15, detail: "≥2× rata-rata: 15 | naik: 8 | memudar (<0,7×): 0 — pembeli hilang" },
      { name: "Open Interest searah",     maxPts: 15, detail: "OI naik ≥3%: 15 (uang baru masuk) | naik tipis: 8 | turun: 0" },
      { name: "Funding belum sesak",      maxPts: 12, detail: "netral: 12 (bahan bakar belum terpakai) | wajar: 6 | sesak: 0" },
      { name: "RSI belum ekstrem",        maxPts: 10, detail: "LONG: RSI < 70 · SHORT: RSI > 30 → 10" },
    ],
    penalties: [
      "Gerbang keras (bukan penalti): Δ24h di luar 5–150% → lewati; likuiditas 24h < $5 jt → lewati (BLUAI −8% → −17% antar-tick)",
      "Funding > 0,25% melawan arah → veto; risiko delisting → veto",
      "Celah data (G14): lilin kosong / volume nol dalam 10 lilin terakhir → lewati",
      "Gerak 30m > 15% searah → size_mult 0,5 (momentum ekstrem dikecilkan, bukan diveto)",
      "R:R < agentic_min_rr (2,0) → lewati",
    ],
  },
];

// ─── FUTURES: LEVERAGE & UKURAN ─────────────────────────────────────────────

export const LEVERAGE_CALC = {
  base: [
    { atr: "basis", base: 6, note: "agen memulai dari 6× lalu di-cap, yang terkecil menang" },
  ],
  caps: [
    { rule: "Batas margin di SL",   formula: "L ≤ lev_lane_cap_default (25%) ÷ risk_pct", note: "rugi di SL ≤ 25% margin" },
    { rule: "Keamanan likuidasi",   formula: "L ≤ 95 ÷ lev_liq_safety_mult (2) ÷ risk_pct", note: "jarak likuidasi ≥ 2× jarak SL" },
    { rule: "Plafon absolut lane",  formula: "L ≤ lev_max_agentic (default lev_max_default = 6)", note: "berlaku di atas semua batas lain" },
    { rule: "Entry terlambat",      formula: "|Δ24h| ≥ 15% → L ÷ 2", note: "risiko pembalikan lebih tinggi" },
  ],
  sizing: [
    { rule: "Risiko per posisi",    formula: "size_risk_base_pct (1%) × modal", note: "notional = risiko ÷ risk_pct" },
    { rule: "Panas portofolio",     formula: "Σ risiko terbuka ≤ size_portfolio_max_risk_pct", note: "posisi baru ditolak bila melampaui" },
    { rule: "Margin dompet",        formula: "Σ margin ≤ max_wallet_margin_pct (70%)", note: "cross-margin, satu dompet" },
  ],
};

// ─── FUTURES: ATURAN KELUAR (exit_rules.py) ──────────────────────────────────
// Urutannya ADALAH aturannya: SL selalu dinilai pertama.

export const FUTURES_MONITOR_LAYERS = [
  {
    label: "0 · SL — selalu pertama",
    emoji: "🛑",
    color: "bg-red-50 border-red-200",
    detail: "Dinilai dari sumbu lilin, ditutup DI HARGA SL (stop order terisi di harga stop).\nSL yang sudah melewati entry menutup sebagai `sl_plus` — untung, bukan kekalahan (risk_gate tak menghitungnya sebagai rentetan rugi).\nsl_breach_pct dicatat: seberapa jauh fill melewati SL.",
  },
  {
    label: "1 · TP1 parsial — 50%",
    emoji: "📊",
    color: "bg-blue-50 border-blue-200",
    detail: "TP1 = entry ± exit_tp1_atr_mult (1,2) × ATR.\nTersentuh → jual 50% (exit_tp1_close_frac), bank untungnya, SL sisa dipindah melindungi.\nFee dipotong PENUH untuk fraksi yang dijual.",
  },
  {
    label: "2 · TP2 parsial — 25%",
    emoji: "🪜",
    color: "bg-indigo-50 border-indigo-200",
    detail: "TP2 = entry ± exit_tp2_atr_mult (2,5) × ATR.\nTersentuh → jual 25% lagi. Sisa 25% jadi PELARI tanpa plafon — satu-satunya sumber kemenangan besar (POWR +12,7%, STEEM +12,1%).",
  },
  {
    label: "3 · Trailing sesudah TP1",
    emoji: "🔒",
    color: "bg-teal-50 border-teal-200",
    detail: "SL = entry ± exit_trail_lock_frac (75%) × puncak untung.\nHanya bergerak MENGUNCI (tak pernah mundur); pemindahan < 1 ppm diabaikan.\nDiperiksa tiap 30 detik oleh jalur cepat.",
  },
  {
    label: "4 · Breakeven — sebelum TP1",
    emoji: "🛡",
    color: "bg-green-50 border-green-200",
    detail: "DUA syarat wajib: untung > exit_be_arm_cost_mult (3×) biaya round-trip DAN > exit_be_arm_atr (0,6) × ATR.\nSL dipindah mengunci exit_be_lock_frac (50%) untung — lantainya entry + biaya, bukan entry telanjang (tiap sentuhan di entry = nol menurut definisi).",
  },
  {
    label: "5 · Time-stop — tesis tak jalan",
    emoji: "⏱",
    color: "bg-amber-50 border-amber-200",
    detail: "Tahan > exit_max_hold_h (8 jam) DAN progres < exit_time_stop_progress (0,5×) risiko → tutup di harga pasar.\nMedian hold pemenang 7,8 jam; yang lebih lama tanpa progres jarang berbalik jadi pemenang.",
  },
  {
    label: "Rekonsiliasi offline",
    emoji: "🔁",
    color: "bg-neutral-50 border-neutral-200",
    detail: "Posisi tanpa denyut > 15 menit (backend mati / laptop tidur) diputar ulang dari lilin 15m.\nHANYA persilangan SL yang ditutup retroaktif (di harga SL, waktu lilin) — parsial/trailing tak disimulasikan.",
  },
];

// ─── FUTURES: RISK GATE ───────────────────────────────────────────────────────

export const RISK_GATE = {
  states: [
    { state: "OPEN",        color: "bg-green-100 text-green-800 border-green-300",   desc: "Drawdown < hard-stop → auto-open normal, max 6 posisi global" },
    { state: "LANE PAUSED", color: "bg-yellow-100 text-yellow-800 border-yellow-300",desc: "1+ lane dijeda karena WR < 35% (lane lain tetap jalan). Jeda BERLIPAT tiap pengulangan: 24 j → 48 j → … maks 168 j, dan bertahan melewati restart" },
    { state: "CLOSED",      color: "bg-red-100 text-red-800 border-red-300",         desc: "Drawdown ≥ hard-stop ATAU Sharpe < −0.5 → semua auto-open stop sampai recovery" },
  ],
  drawdownThresholds: [
    { wallet: "< $500",   hardStop: "10%", recover: "5%"  },
    { wallet: "< $750",   hardStop: "12%", recover: "6%"  },
    { wallet: "< $1500",  hardStop: "15%", recover: "8%",  note: "default ($1000)" },
    { wallet: "≥ $1500",  hardStop: "20%", recover: "10%" },
  ],
  rarGate: {
    formula: "Sharpe proxy = mean / stdev dari 20 trade TERAKHIR (rolling, PLAN_v11)",
    trigger: "Sharpe < −0.5 DAN n ≥ 10 → CLOSED. Anti-deadlock: probe ½-risk tiap 6 jam saat aktif (hasilkan data pemulih); ambang longgar −0.8 saat regime bullish & DD rendah",
  },
  laneWRPause: {
    rolling: 20,
    threshold: "WR < 35%",
    duration: "24 j → 48 j → … maks 168 j",
    desc: "Per-lane auto-pause jika win rate rolling 20 trade < 35%. Cegah death spiral satu style. Jeda BERLIPAT tiap kali lane dijeda ulang tanpa sempat membaik, dan tersimpan di DB sehingga restart tak mengosongkan hitungannya — sebelum diperbaiki, jeda 24 jam bisa buyar dalam 2 jam dan eskalasinya tak pernah tercapai. Lane yang membaik mereset hitungan.",
  },
};

// ─── ADAPTIVE LEARNING ───────────────────────────────────────────────────────

export const ADAPTIVE_LEARNING = {
  overview: "Setiap trade selesai (TP/SL/expired) → update weight sinyal yang aktif saat trade dibuka → scan berikutnya pakai weight baru.",
  spotDecay: { halfLife: "7 hari",  window: "30 hari", note: "Spot berubah cepat" },
  futuresDecay: { halfLife: "14 hari", window: "30 hari", note: "Futures lebih slow-moving" },
  minSample: 3,
  stepCap: "±10% per run",
  weightFormula: [
    { wr: "≥ 70%", target: 1.5, note: "↑ boost 50%" },
    { wr: "≥ 55%", target: 1.2, note: "↑ boost 20%" },
    { wr: "≥ 40%", target: 1.0, note: "neutral"     },
    { wr: "< 40%", target: 0.7, note: "↓ penalize 30%" },
  ],
  laplace: "win_rate_adj = (wins + 1) / (n_eff + 2)  ← Laplace smoothing untuk avoid over-fit sample kecil",
  confidence: "confidence = min(1.0, n_eff / 10.0)  ← makin banyak sample makin percaya",
  futuresThresholds: [
    { condition: "n < 30",            minScore: 52, autoThreshold: 72, note: "wait for sample" },
    { condition: "WR < 40%",          minScore: 56, autoThreshold: 75, note: "lebih ketat" },
    { condition: "WR 40–55%",         minScore: 54, autoThreshold: 74 },
    { condition: "WR 55–65%",         minScore: 52, autoThreshold: 72, note: "normal" },
    { condition: "WR > 65% AND n≥50", minScore: 50, autoThreshold: 70, note: "proven, relaxed" },
  ],
  coinBlacklist: {
    trigger: "3 trade terakhir pada coin yang sama → semua SL",
    action: "Blacklist coin tersebut selama 24 jam (directional)",
    why: "Cegah death spiral: agent terus masuk di coin yang memang lagi broken.",
  },
  coinWRBonus: [
    { condition: "Riwayat ≥ 3 trade, WR ≥ 70%", bonus: "+5 pts" },
    { condition: "Riwayat ≥ 3 trade, WR < 30%",  bonus: "-5 pts" },
    { condition: "Riwayat < 3 trade",             bonus: "0 pts (belum ada data)" },
  ],
};

// ─── TECH STACK ──────────────────────────────────────────────────────────────

export const TECH_STACK = [
  {
    layer: "Frontend",
    icon: "🖥",
    color: "bg-blue-50 border-blue-200",
    items: ["Next.js 16 (App Router)", "TypeScript strict", "Tailwind CSS v4", "Recharts (equity curve)", "WebSocket live updates", "Browser Notification API"],
  },
  {
    layer: "Backend",
    icon: "⚙️",
    color: "bg-purple-50 border-purple-200",
    items: ["FastAPI + Python 3.12", "SQLAlchemy async + asyncpg", "PostgreSQL 16 (paper trades)", "Redis 7 (cache + pub/sub)", "HTTPX (Binance REST)", "Structlog (structured logs)"],
  },
  {
    layer: "TA Engine (T0–T4)",
    icon: "🔭",
    color: "bg-teal-50 border-teal-200",
    items: ["T0: Wyckoff phase detection", "T1: EMA/ADX trend analysis", "T2: S/R swing pivot zones", "T3: BB/Vol/RSI/candle patterns", "T4: Trigger confirmation", "ATR + Fibonacci fallback"],
  },
  {
    layer: "Agents & Infra",
    icon: "🤖",
    color: "bg-amber-50 border-amber-200",
    items: ["7 asyncio background agents", "Binance Spot + Futures REST", "Adaptive signal weight system", "Docker Compose (local dev)", "Lifespan-embedded agents", "Health endpoint per agent"],
  },
];
