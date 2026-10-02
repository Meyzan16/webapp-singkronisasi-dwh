"use client";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

interface Stats {
  n: number; r_per_trade: number | null; tp_rate: number | null;
  profit_factor: number | null; median_hold_min: number | null;
}
interface Check { rule: string; ok: boolean; value: string }
interface Group {
  hypothesis: string; direction: string; description: string; pending: number; is_control: boolean;
  all: Stats; first_half: Stats; second_half: Stats;
  checks: Check[]; passed: boolean; edge_vs_control: number | null;
}
interface Report {
  started_at: number | null; labelled: number; pending: number; control_r_per_trade: number;
  rules: { min_n: number; min_r_half: number; min_edge_vs_control: number; max_week_share: number; min_events_rel_strength?: number };
  groups: Group[]; generated_at: number;
}

const REFRESH_MS = 120_000;

function fmtR(v: number | null | undefined): string {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}R`;
}
function rCls(v: number | null | undefined): string {
  if (v == null) return "text-neutral-400";
  return v > 0 ? "text-green-600" : v < 0 ? "text-red-500" : "text-neutral-600";
}

/**
 * Hasil riset sinyal shadow futures (PLAN-OKT-2026 P1a): hipotesis entry
 * alternatif yang direkam tanpa membuka posisi, dinilai dengan bracket SL/TP.
 * Aturan lulus ditetapkan sebelum ada hasil — UI hanya menampilkan, tak mengubah.
 */
export function ShadowResearchTab() {
  const [data, setData] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await apiFetch("/api/v1/futures/shadow-report");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json() as Report);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "gagal memuat");
    }
  }, []);

  useEffect(() => {
    // Muat pertama ditunda satu tick supaya tidak setState sinkron di dalam effect.
    const first = setTimeout(() => { void load(); }, 0);
    const id = setInterval(() => { void load(); }, REFRESH_MS);
    return () => { clearTimeout(first); clearInterval(id); };
  }, [load]);

  if (error && !data) return <p className="text-xs text-neutral-400 px-1">Riset shadow tidak terbaca: {error}</p>;
  if (!data) return <p className="text-xs text-neutral-400 px-1">Memuat riset shadow...</p>;

  const ctrl = data.groups.find(g => g.is_control);
  const tests = data.groups.filter(g => !g.is_control);
  const days = data.started_at ? Math.max(0, (data.generated_at - data.started_at) / 86400) : 0;
  const passed = tests.filter(g => g.passed);

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl border border-neutral-200 p-5 space-y-2">
        <h3 className="font-bold text-sm text-neutral-700">🧪 Riset sinyal alternatif (shadow)</h3>
        <p className="text-xs text-neutral-500">
          Agen futures sekarang belum punya keunggulan saat memilih titik masuk. Halaman ini menguji ide masuk lain
          <span className="font-semibold"> tanpa membuka posisi</span>: tiap sinyal dicatat lalu dinilai seolah ditradingkan
          dengan SL 1,5×ATR dan TP 3×ATR (target 2R) selama 24 jam, sudah dipotong biaya 0,3%.
          Hasil dalam <span className="font-semibold">R</span> = kelipatan risiko per trade (+1R = untung sebesar risikonya).
        </p>
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs pt-1">
          <span>Berjalan <span className="font-bold">{days.toFixed(1)} hari</span></span>
          <span>Sudah dinilai <span className="font-bold">{data.labelled}</span> · menunggu <span className="font-bold">{data.pending}</span></span>
          <span>Pembanding acak <span className={`font-bold ${rCls(ctrl?.all.r_per_trade)}`}>{fmtR(ctrl?.all.r_per_trade)}</span>/trade</span>
          <span className={passed.length ? "text-green-600 font-bold" : "text-neutral-500"}>
            {passed.length ? `✅ ${passed.length} hipotesis LULUS` : "Belum ada hipotesis yang lulus"}
          </span>
        </div>
        <p className="text-[11px] text-neutral-400">
          Syarat lulus (dikunci sebelum ada hasil): ≥{data.rules.min_n} sinyal · paruh awal &amp; akhir masing-masing &gt; +{data.rules.min_r_half}R ·
          ≥{data.rules.min_edge_vs_control}R di atas pembanding · satu minggu ≤{Math.round(data.rules.max_week_share * 100)}% total R
          {data.rules.min_events_rel_strength ? ` · rel_strength juga harus berasal dari ≥${data.rules.min_events_rel_strength} kejadian pasar terpisah (satu penurunan BTC memicu puluhan sinyal sekaligus)` : ""}.
          Di bawah ±100 sinyal angka masih sangat dipengaruhi kebetulan.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {tests.map(g => {
          const progress = Math.min(100, (g.all.n / data.rules.min_n) * 100);
          return (
            <div key={`${g.hypothesis}-${g.direction}`}
              className={`bg-white rounded-2xl border p-4 space-y-3 ${g.passed ? "border-green-300" : "border-neutral-200"}`}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-bold text-sm">
                    {g.hypothesis}{" "}
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${g.direction === "LONG" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>{g.direction}</span>
                  </p>
                  <p className="text-[11px] text-neutral-500 mt-0.5">{g.description}</p>
                </div>
                <span className={`text-[10px] font-black px-2 py-0.5 rounded shrink-0 ${g.passed ? "bg-green-100 text-green-700" : "bg-neutral-100 text-neutral-500"}`}>
                  {g.passed ? "LULUS" : "BELUM"}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <p className="text-[10px] text-neutral-400">Hasil/trade</p>
                  <p className={`font-black text-sm tabular-nums ${rCls(g.all.r_per_trade)}`}>{fmtR(g.all.r_per_trade)}</p>
                </div>
                <div>
                  <p className="text-[10px] text-neutral-400">vs pembanding</p>
                  <p className={`font-black text-sm tabular-nums ${rCls(g.edge_vs_control)}`}>{fmtR(g.edge_vs_control)}</p>
                </div>
                <div>
                  <p className="text-[10px] text-neutral-400">Kena TP</p>
                  <p className="font-black text-sm tabular-nums">{g.all.tp_rate == null ? "–" : `${g.all.tp_rate.toFixed(0)}%`}</p>
                </div>
              </div>

              <div>
                <div className="flex justify-between text-[10px] text-neutral-400 mb-1">
                  <span>Data: {g.all.n} / {data.rules.min_n} sinyal</span>
                  <span>{g.pending} menunggu dinilai</span>
                </div>
                <div className="h-1.5 bg-neutral-100 rounded-full overflow-hidden">
                  <div className="h-full bg-teal-400 rounded-full" style={{ width: `${progress}%` }} />
                </div>
              </div>

              <ul className="space-y-0.5">
                {g.checks.map(c => (
                  <li key={c.rule} className="flex justify-between text-[11px]">
                    <span className={c.ok ? "text-green-600" : "text-neutral-500"}>{c.ok ? "✓" : "✗"} {c.rule}</span>
                    <span className="font-mono text-neutral-500">{c.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
