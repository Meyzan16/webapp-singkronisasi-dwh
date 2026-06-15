import { Card, CardContent } from "@/components/ui/card";
import { Code, SectionTitle } from "./primitives";

const STATUSES = [
  { s: "🔵 open",    c: "bg-blue-50 border-blue-200",       t: "Posisi Aktif",    d: "User sudah buka, monitor sedang track harga. Unrealized P&L live dari Binance." },
  { s: "✅ tp",      c: "bg-green-50 border-green-200",     t: "TP Hit",          d: "Harga mencapai TP2 atau TP3. Ditutup otomatis, dihitung sebagai Win." },
  { s: "🛑 sl",      c: "bg-red-50 border-red-200",         t: "SL Hit",          d: "Harga turun ke level SL. Ditutup otomatis, dihitung sebagai Loss." },
  { s: "🤚 manual",  c: "bg-neutral-50 border-neutral-200", t: "Tutup Manual",    d: "User menutup sendiri di harga pasar saat itu." },
  { s: "🟡 tp1_hit", c: "bg-yellow-50 border-yellow-200",   t: "TP1 Tersentuh",   d: "TP1 sudah kena tapi posisi tetap open — ride ke TP2." },
];

const RULES = [
  { t: "Per-coin rule",    d: "1 posisi open per koin. Koin berbeda boleh bersamaan." },
  { t: "Entry validation", d: "Entry tidak boleh > 2% dari harga pasar saat buka posisi." },
  { t: "R:R minimum",      d: "R:R ke TP2 ≥ 2.0. Koin yang tidak memenuhi dibuang." },
  { t: "SL max 8%",        d: "Stop loss tidak boleh lebih dari 8% dari entry." },
];

const LIFECYCLE_CODE = `Layer 1: Scanner menemukan koin (score ≥ 30)
         │  BB Squeeze + Vol + RSI + Taker ratio
         │  Tersimpan di opportunity store (WS)
         ▼
Layer 2: User klik koin → Analyzer jalan (~2s)
         │  ATR-based SL · Resistance-based TP
         │  Order book depth ratio
         │  Confidence score 0–99
         ▼
Layer 3: User klik "Buka Posisi SPOT"
         │  Validasi: entry dalam 2% market price
         │  Validasi: tidak ada posisi koin ini
         │  Simpan ke paper_trades (status=open)
         ▼
Layer 3b: Monitor cek setiap 60 detik
         │
         ├── harga ≤ SL  → status='sl'
         ├── harga ≥ TP2 → status='tp'
         ├── harga ≥ TP3 → status='tp' (close=TP3)
         └── harga ≥ TP1 (pertama) → tp1_hit=True
                                      posisi tetap OPEN
         │
         ▼
Layer 4: History → Opportunity SPOT tab
         Win rate · Avg P&L · Per-type analytics
         Score vs Outcome · Export CSV`;

export function SpotLifecycleCard() {
  return (
    <Card>
      <CardContent className="pt-5">
        <SectionTitle icon="🎯" title="Opportunity SPOT — Siklus Posisi" sub="Dari scanner → analisis → buka → monitor → history" />

        <div className="grid md:grid-cols-2 gap-6">
          <Code>{LIFECYCLE_CODE}</Code>
          <div className="space-y-2">
            <p className="text-sm font-bold text-neutral-800 mb-3">Status Posisi</p>
            {STATUSES.map(s => (
              <div key={s.s} className={`rounded-xl border p-3 ${s.c}`}>
                <div className="flex items-center gap-2 mb-1">
                  <code className="font-bold text-xs">{s.s}</code>
                  <span className="text-[10px] text-neutral-500">{s.t}</span>
                </div>
                <p className="text-xs text-neutral-600">{s.d}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-4 bg-neutral-900 text-white rounded-xl p-4 text-xs">
          <p className="font-bold text-teal-400 mb-2">✅ Aturan Posisi Opportunity SPOT</p>
          <div className="grid md:grid-cols-4 gap-3">
            {RULES.map(r => (
              <div key={r.t}>
                <p className="font-semibold text-neutral-300 mb-1">{r.t}</p>
                <p className="text-neutral-500">{r.d}</p>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
