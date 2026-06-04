export function SLTPGuide() {
  return (
    <div className="space-y-4">
      {/* Overview */}
      <div className="bg-neutral-900 text-white rounded-xl p-5">
        <p className="font-bold text-teal-400 mb-2">📏 Sistem Entry + SL + TP</p>
        <p className="text-sm text-neutral-300 leading-relaxed mb-3">
          Scanner menggunakan <strong className="text-yellow-300">3 tahap berurutan</strong>:
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="bg-yellow-900/30 border border-yellow-700/40 rounded-lg p-3">
            <p className="text-yellow-300 font-bold text-xs mb-1">① ENTRY — Zone Based</p>
            <p className="text-[11px] text-neutral-300">LONG → masuk di <strong>support terkuat</strong><br />SHORT → masuk di <strong>resistance terkuat</strong><br />Jika harga sudah di zona → entry sekarang<br />Jika belum → pasang limit order di zona</p>
          </div>
          <div className="bg-red-900/30 border border-red-700/40 rounded-lg p-3">
            <p className="text-red-300 font-bold text-xs mb-1">② SL — TA Hierarchy</p>
            <p className="text-[11px] text-neutral-300">1. S/R zone − 0.3% buffer<br />2. Swing low/high struktural<br />3. Fibonacci 0.618 retracement<br />4. ATR × multiplier (fallback)<br /><strong className="text-red-400">+ Min jarak per style (0.8–3%)</strong></p>
          </div>
          <div className="bg-green-900/30 border border-green-700/40 rounded-lg p-3">
            <p className="text-green-300 font-bold text-xs mb-1">③ TP — TA Hierarchy</p>
            <p className="text-[11px] text-neutral-300">1. S/R zone berikutnya (R:R ≥ 1:2)<br />2. Fibonacci 1.618 extension<br />3. ATR × multiplier (fallback)<br /><strong className="text-green-400">Filter: R:R &lt; min per style = buang</strong></p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* SL Card */}
        <div className="bg-white border-2 border-red-200 rounded-xl overflow-hidden">
          <div className="bg-red-50 px-4 py-3 border-b border-red-200">
            <p className="font-bold text-red-700">⛔ Stop Loss — Prioritas Urutan</p>
            <p className="text-xs text-red-500 mt-0.5">Diambil dari metode tertinggi yang valid</p>
          </div>
          <div className="p-4 space-y-4">
            {SL_STEPS.map(({ num, bg, title, code, note }) => (
              <div key={num} className="flex gap-3">
                <div className={`w-6 h-6 rounded-full ${bg} text-white flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5`}>{num}</div>
                <div>
                  <p className="font-semibold text-sm">{title}</p>
                  <pre className="text-[11px] font-mono bg-neutral-900 text-green-400 p-2.5 rounded-lg mt-1.5 whitespace-pre-wrap">{code}</pre>
                  <p className="text-xs text-neutral-500 mt-1">{note}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* TP Card */}
        <div className="bg-white border-2 border-green-200 rounded-xl overflow-hidden">
          <div className="bg-green-50 px-4 py-3 border-b border-green-200">
            <p className="font-bold text-green-700">🎯 Take Profit — Prioritas Urutan</p>
            <p className="text-xs text-green-500 mt-0.5">Minimum R:R 1:1.5 wajib terpenuhi</p>
          </div>
          <div className="p-4 space-y-4">
            {TP_STEPS.map(({ num, bg, title, code, note }) => (
              <div key={num} className="flex gap-3">
                <div className={`w-6 h-6 rounded-full ${bg} text-white flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5`}>{num}</div>
                <div>
                  <p className="font-semibold text-sm">{title}</p>
                  <pre className="text-[11px] font-mono bg-neutral-900 text-green-400 p-2.5 rounded-lg mt-1.5 whitespace-pre-wrap">{code}</pre>
                  <p className="text-xs text-neutral-500 mt-1">{note}</p>
                </div>
              </div>
            ))}
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
              <p className="text-xs font-bold text-amber-700 mb-2">⚖️ Validasi R:R — Filter per Style</p>
              <pre className="text-[11px] font-mono text-amber-800 whitespace-pre-wrap">{RR_VALIDATION}</pre>
            </div>
          </div>
        </div>
      </div>

      {/* Entry zone logic */}
      <div className="bg-white border-2 border-yellow-300 rounded-xl overflow-hidden">
        <div className="bg-yellow-50 px-4 py-3 border-b border-yellow-200">
          <p className="font-bold text-yellow-700">🎯 Entry Zone — LONG di Support, SHORT di Resistance</p>
          <p className="text-xs text-yellow-600 mt-0.5">Entry bukan di harga pasar, tapi di zona S/R terkuat</p>
        </div>
        <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="font-semibold text-sm mb-2">🟢 LONG — Entry di Support</p>
            <pre className="text-[11px] font-mono bg-neutral-900 text-green-400 p-3 rounded-lg whitespace-pre-wrap">{ENTRY_LONG}</pre>
          </div>
          <div>
            <p className="font-semibold text-sm mb-2">🔴 SHORT — Entry di Resistance</p>
            <pre className="text-[11px] font-mono bg-neutral-900 text-green-400 p-3 rounded-lg whitespace-pre-wrap">{ENTRY_SHORT}</pre>
          </div>
        </div>
        <div className="px-4 pb-4">
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
            <p className="text-xs font-bold text-yellow-700 mb-1">💡 Kenapa entry di zona S/R, bukan market price?</p>
            <p className="text-xs text-yellow-800 leading-relaxed">
              Masuk di support/resistance memberikan <strong>risk:reward terbaik</strong> karena SL bisa sangat dekat
              dengan zona (−0.3%), sedangkan TP bisa jauh ke resistance berikutnya.
              Masuk di market price random = SL bisa terlalu jauh dari support, R:R menjadi buruk.
            </p>
          </div>
        </div>
      </div>

      {/* Flowchart */}
      <div className="bg-neutral-900 text-white rounded-xl p-5">
        <p className="font-bold text-teal-400 mb-3">🔄 Alur Lengkap Entry → SL → TP</p>
        <div className="space-y-2 text-xs font-mono">
          {FLOWCHART.map((step, i) => (
            <div key={i} className="flex gap-3 items-start">
              <span className={`font-bold flex-shrink-0 ${step.color}`}>{step.label}</span>
              <span className="text-neutral-500">→ {step.detail}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Static content ─────────────────────────────────────────────────────────────

const SL_STEPS = [
  {
    num: 1, bg: "bg-red-600", title: "S/R Zone (Support/Resistance)",
    code: `Deteksi swing highs/lows (2 bar kiri-kanan)
Cluster level dalam 0.5% → zona

LONG:  SL = NearestSupport × (1 − 0.003)
         = Support terdekat di bawah entry − 0.3% buffer
SHORT: SL = NearestResistance × (1 + 0.003)
         = Resistance terdekat di atas entry + 0.3% buffer

Kenapa 0.3% buffer?
Hindari stop-hunt (market maker gerakkan harga
sejenak menyentuh support sebelum naik)`,
    note: "✅ Paling akurat — berbasis struktur market nyata",
  },
  {
    num: 2, bg: "bg-red-500", title: "Structural Swing Low/High",
    code: `LONG:  SL = Min(Low[-lookback:]) × 0.997
SHORT: SL = Max(High[-lookback:]) × 1.003

Dipakai jika S/R zone tidak ditemukan,
atau S/R zone terlalu jauh (> 8% dari entry)`,
    note: "✅ Berbasis struktur swing market",
  },
  {
    num: 3, bg: "bg-red-400", title: "Fibonacci Retracement 0.618",
    code: `Swing Range = SwingHigh − SwingLow

LONG:  SL = Entry − SwingRange × 0.618
SHORT: SL = Entry + SwingRange × 0.618

Golden ratio (0.618) = level retracement terkuat
di mana harga sering berbalik arah`,
    note: "✅ Level institusional — banyak order di sini",
  },
  {
    num: 4, bg: "bg-neutral-400", title: "ATR Fallback",
    code: `ATR(14) = Avg(TrueRange[-14:])
TrueRange = max(H−L, |H−Close_prev|, |L−Close_prev|)

LONG:  SL = Entry − ATR × style_multiplier
SHORT: SL = Entry + ATR × style_multiplier

Multiplier: Scalping×1.0 | DayTrade×1.2 | Swing×1.5 | Position×2.0`,
    note: "⚠️ Dipakai hanya jika semua metode di atas gagal",
  },
];

const TP_STEPS = [
  {
    num: 1, bg: "bg-green-600", title: "Resistance/Support Zone Berikutnya",
    code: `LONG:  Cari resistance zone di atas entry
         Pilih yang memberikan R:R ≥ 1:2
SHORT: Cari support zone di bawah entry
         Pilih yang memberikan R:R ≥ 1:2

Kenapa R:R ≥ 1:2?
Minimum reward harus 2× risiko agar
profitable secara statistik (win rate 40% cukup)`,
    note: "✅ Paling realistic — target di mana harga pernah terhenti",
  },
  {
    num: 2, bg: "bg-green-500", title: "Fibonacci Extension 1.618",
    code: `Digunakan saat tidak ada resistance zone
yang memberikan R:R ≥ 1:2

LONG:  TP = Entry + (Entry − SwingLow) × 1.618
SHORT: TP = Entry − (SwingHigh − Entry) × 1.618

Level Fibonacci extension standar:
  1.272 = conservative target
  1.618 = golden ratio (paling sering tercapai) ← dipakai
  2.618 = aggressive target`,
    note: "✅ Level institusional — banyak profit-taking di sini",
  },
  {
    num: 3, bg: "bg-neutral-400", title: "ATR Fallback",
    code: `LONG:  TP = Entry + ATR × style_multiplier
SHORT: TP = Entry − ATR × style_multiplier

Multiplier: Scalping×2.5 | DayTrade×3.0 | Swing×4.5 | Position×7.0`,
    note: "⚠️ Dipakai hanya jika S/R dan Fibonacci tidak valid",
  },
];

const RR_VALIDATION = `Risk   = |Entry − SL|
Reward = |TP − Entry|
R:R    = Reward / Risk

Minimum R:R per trading style:
  Scalping  → R:R ≥ 1:1.5
  Day Trade → R:R ≥ 1:1.8
  Swing     → R:R ≥ 1:2.0
  Position  → R:R ≥ 1:2.5

Setup yang tidak memenuhi → otomatis dibuang`;

const ENTRY_LONG = `Support zone = Max swing low cluster
               di bawah harga saat ini

Dist = (price − support) / support

Jika dist ≤ 1.5%:
  ✅ at_zone → entry sekarang (market order)

Jika dist 1.5–6%:
  ⏳ wait_pullback → entry = support midpoint
  Pasang LIMIT BUY di zona support

Jika dist > 6%:
  ⚠️ wait_pullback → terlalu jauh
  Tunggu pullback signifikan dulu

SL = di bawah support zone (−0.3% buffer)
TP = resistance zone berikutnya di atas`;

const ENTRY_SHORT = `Resistance zone = Min swing high cluster
                  di atas harga saat ini

Dist = (resistance − price) / resistance

Jika dist ≤ 1.5%:
  ✅ at_zone → entry sekarang (market order)

Jika dist 1.5–6%:
  ⏳ wait_rally → entry = resistance midpoint
  Pasang LIMIT SELL di zona resistance

Jika dist > 6%:
  ⚠️ wait_rally → terlalu jauh
  Tunggu rally ke resistance dulu

SL = di atas resistance zone (+0.3% buffer)
TP = support zone berikutnya di bawah`;

const FLOWCHART = [
  { label: "① Deteksi S/R zones", detail: "swing pivot 2-bar → cluster dalam 0.5%", color: "text-yellow-400" },
  { label: "② Tentukan ENTRY",    detail: "LONG=support, SHORT=resistance | at_zone / wait_pullback / wait_rally", color: "text-green-400" },
  { label: "③ Hitung SL",         detail: "S/R zone −0.3% → swing low → Fib 0.618 → ATR fallback", color: "text-red-400" },
  { label: "④ Enforce min SL",    detail: "Scalp≥0.8% / DayTrade≥1.2% / Swing≥2.0% / Position≥3.0%", color: "text-orange-400" },
  { label: "⑤ Hitung TP",         detail: "S/R berikutnya (R:R≥1:2) → Fib 1.618 → ATR fallback", color: "text-blue-400" },
  { label: "⑥ Filter R:R",        detail: "Scalp≥1:1.5 / DayTrade≥1:1.8 / Swing≥1:2.0 / Position≥1:2.5", color: "text-purple-400" },
  { label: "⑦ Tampilkan",         detail: "entry_type + entry_note + entry_zone + SL method + TP method", color: "text-teal-400" },
];
