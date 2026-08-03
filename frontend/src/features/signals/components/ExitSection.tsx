"use client";
/**
 * Seksi EXIT — sisi KELUAR dari Adaptive Learning Engine (M6).
 *
 * Lima seksi lain di halaman ini semuanya bercerita tentang keputusan MASUK
 * (bobot sinyal, model entry, repair sinyal). Padahal bukti menunjukkan kerugian
 * futures berasal dari keputusan KELUAR: TP tersentuh 1 dari 44 posisi.
 *
 * Seluruh pekerjaan M0–M5 (ledger keluar, analisa pemicu, lebar SL, tahapan
 * penyalaan) sebelumnya hanya bisa dilihat lewat endpoint API. Seksi ini
 * memberinya halaman.
 *
 * Aturan yang dipegang komponen ini:
 *   • TIDAK ada daftar lane yang ditulis di sini — lane tumbuh dari respons API.
 *   • TIDAK ada ambang yang ditulis di sini — gate & syarat datang dari API,
 *     supaya angka di layar tak pernah berbeda dari angka yang dipakai mesin.
 *   • Data hasil backfill DITANDAI, karena alasan close-nya hasil pemulihan dari
 *     riwayat, bukan catatan langsung monitor.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { futuresLaneLabel } from "@/lib/agents";
import { laneForSpot } from "@/lib/lanes";

export type ExitSubTab = "exit_reasons" | "exit_triggers" | "exit_sl" | "exit_rollout";

// ── Dimensi MARKET ────────────────────────────────────────────────────────────
// FUTURES dan SPOT dilayani komponen yang SAMA, dibedakan hanya oleh peta di
// bawah. Endpoint-nya pun berbagi implementasi di backend (argumen `market`),
// jadi perbaikan pada analisa otomatis berlaku untuk keduanya.
//
// Ini disengaja: sisi SPOT di proyek ini berulang kali dibangun sebagai salinan
// terpisah lalu menyimpang diam-diam — katalog Formulas dan tab Predictive
// dua-duanya sempat futures-only tanpa satu pun error muncul.
//
// `null` pada sebuah endpoint = kemampuan itu memang belum ada untuk market
// tersebut, dan UI menyatakannya terus terang alih-alih meminjam angka market
// lain.

export type ExitMarket = "futures" | "spot";

interface MarketSpec {
  key: ExitMarket;
  label: string;
  icon: string;
  /** Endpoint per kebutuhan. `null` = belum tersedia untuk market ini. */
  endpoints: {
    analysis: string | null;
    triggers: string | null;
    slWidth:  string | null;
    rollout:  string | null;
  };
  /** Nama ramah untuk sebuah lane di market ini. */
  laneLabel: (lane: string) => string;
  /** Ditampilkan saat market belum punya ledger — menjelaskan apa yang kurang. */
  pending?: string;
}

const MARKETS: MarketSpec[] = [
  {
    key: "futures", label: "FUTURES", icon: "⚡",
    endpoints: {
      analysis: "/api/v1/futures/exit-learning/analysis",
      triggers: "/api/v1/futures/exit-learning/triggers",
      slWidth:  "/api/v1/futures/exit-learning/sl-width",
      rollout:  "/api/v1/futures/exit-rollout",
    },
    laneLabel: futuresLaneLabel,
  },
  {
    key: "spot", label: "SPOT", icon: "🎯",
    endpoints: {
      analysis: "/api/v1/spot/exit-learning/analysis",
      triggers: "/api/v1/spot/exit-learning/triggers",
      slWidth:  "/api/v1/spot/exit-learning/sl-width",
      // Tahapan penyalaan menyetel parameter monitor FUTURES; SPOT belum punya
      // parameter keluar yang bisa ditala, jadi sengaja kosong daripada
      // menampilkan tahapan milik market lain.
      rollout:  null,
    },
    // Nilai lane SPOT di ledger berupa alert_type mentah (`squeeze`,
    // `bigmover_chase`, `breakout_pump`, …). `laneForSpot` sudah jadi pemetanya
    // di seluruh UI — dipakai ulang di sini supaya nama lane SPOT tak pernah
    // punya dua versi yang bisa berbeda.
    laneLabel: (lane) => laneForSpot(lane).label,
  },
];

// ── Kontrak API ───────────────────────────────────────────────────────────────

interface Bucket {
  key?: string;
  n: number;
  expectancy_pct: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  mfe_atr_median: number | null;
  held_hours_median: number | null;
  premature_frac: number | null;
}

interface AnalysisResponse {
  status: string;
  n?: number;
  window_days?: number;
  overall?: Bucket;
  by_close_reason?: Bucket[];
  by_lane?: Bucket[];
  by_regime?: Bucket[];
}

interface TriggerRow {
  lane: string;
  trigger: string;
  n: number;
  win_rate: number | null;
  expectancy_pct: number | null;
  realized_atr_median: number | null;
  sl_dist_atr_median: number | null;
  sl_gap_median: number | null;
  no_saving_frac: number | null;
  from_backfill: boolean;
}

interface TriggersResponse {
  status: string;
  n?: number;
  triggers?: TriggerRow[];
  min_samples?: number;
}

interface SlLaneRow {
  lane: string;
  n: number;
  atr_pct_median: number;
  sl_pct_median: number;
  sl_atr_median: number;
  cv_sl_pct: number | null;
  cv_sl_atr: number | null;
  /** null bila market ini belum punya batas SL yang dikonfigurasi. */
  configured_max_pct: number | null;
  configured_floor_pct: number | null;
  pinned_at_max_frac: number | null;
  pinned_at_floor_frac: number | null;
  sl_vs_mfe: number | null;
  win_rate: number | null;
  expectancy_pct: number | null;
}

interface SlWidthResponse {
  status: string;
  lanes?: SlLaneRow[];
  cv_sl_pct_all?: number | null;
  cv_sl_atr_all?: number | null;
  verdict?: string | null;
  note?: string;
}

interface RolloutRow {
  id: number;
  lane: string;
  param: string;
  stage: string;
  proposed_value: number;
  previous_value: number;
  baseline: { n: number; expectancy_pct: number | null; win_rate: number | null };
  observed: { n: number; expectancy_pct: number | null; win_rate: number | null };
  created_at: number;
  activated_at: number | null;
  decided_at: number | null;
  reason: string;
}

interface RolloutResponse {
  status: string;
  learning_enabled?: boolean;
  note?: string;
  gates?: Record<string, number>;
  rollouts?: RolloutRow[];
}

// ── Penyaji kecil ─────────────────────────────────────────────────────────────

const pct = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : `${v.toFixed(digits)}%`;

const num = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(digits);

const frac = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;

/**
 * Ambang PEWARNAAN — murni tampilan, tidak dipakai mesin untuk memutuskan apa pun.
 *
 * Dikumpulkan di sini alih-alih diselipkan di tengah JSX supaya jelas mana angka
 * yang datang dari API (semua ambang keputusan) dan mana yang sekadar menandai
 * baris agar mata cepat menemukannya. Kalau suatu saat backend menerbitkan
 * ambangnya sendiri, cukup ganti nilai-nilai ini dengan field dari respons.
 */
const SOROT = {
  /** Gap di bawah ini = pemicu nyaris berimpit dengan SL. */
  gapSempit: 1.5,
  /** Porsi mentok plafon di atas ini = rumus ATR jarang benar-benar berlaku. */
  seringMentok: 0.5,
  /** SL sekian kali lebih jauh dari gerak untung nyata = risiko timpang. */
  slJauhDariMfe: 3,
} as const;

/** Hijau bila menguntungkan, merah bila merugikan, netral bila belum ada data. */
const pnlTone = (v: number | null | undefined) =>
  v === null || v === undefined ? "text-neutral-400"
    : v > 0 ? "text-emerald-600" : v < 0 ? "text-rose-600" : "text-neutral-600";

/**
 * Alasan close hasil backfill diberi awalan `hist:` oleh backend. Awalan itu
 * ditampilkan sebagai lencana terpisah — bukan dibuang — supaya pembaca tahu
 * angka itu berasal dari pemulihan riwayat, bukan catatan langsung monitor.
 */
function ReasonLabel({ value }: { value: string }) {
  const recovered = value.startsWith("hist:");
  const clean = recovered ? value.slice(5) : value;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="font-mono text-[11px]">{clean}</span>
      {recovered && (
        <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-200"
          title="Alasan dipulihkan dari riwayat trade lama, bukan dicatat langsung oleh monitor">
          dipulihkan
        </span>
      )}
    </span>
  );
}

/** Label lane mengikuti market aktif — SPOT dan FUTURES punya katalog berbeda. */
function LaneBadge({ lane, market }: { lane: string; market: MarketSpec }) {
  const label = market.laneLabel(lane);
  return (
    <span className="text-[11px] font-bold text-neutral-700">
      {label}
      {label !== lane && <span className="ml-1 font-normal text-neutral-400">({lane})</span>}
    </span>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-center py-10 text-sm text-neutral-400">{children}</div>
  );
}

function Panel({ title, sub, children }: {
  title: string; sub?: string; children: React.ReactNode;
}) {
  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <p className="text-sm font-black text-neutral-800">{title}</p>
      {sub && <p className="text-[11px] text-neutral-500 mt-0.5 leading-relaxed">{sub}</p>}
      <div className="mt-3">{children}</div>
    </div>
  );
}

// ── Seksi ─────────────────────────────────────────────────────────────────────

export function ExitSection({ subTab }: { subTab: ExitSubTab }) {
  const [marketKey, setMarketKey] = useState<ExitMarket>("futures");
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [triggers, setTriggers] = useState<TriggersResponse | null>(null);
  const [slWidth, setSlWidth] = useState<SlWidthResponse | null>(null);
  const [rollout, setRollout] = useState<RolloutResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const market = useMemo(
    () => MARKETS.find(m => m.key === marketKey) ?? MARKETS[0], [marketKey]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    // Market tanpa endpoint dikosongkan secara eksplisit — JANGAN biarkan data
    // market sebelumnya tertinggal di layar dan terbaca sebagai milik market ini.
    setAnalysis(null); setTriggers(null); setSlWidth(null); setRollout(null);
    const { endpoints } = market;
    try {
      const get = async (url: string | null) => {
        if (!url) return null;
        const res = await fetch(url);
        return res.ok ? await res.json() : null;
      };
      const [a, t, s, r] = await Promise.all([
        get(endpoints.analysis), get(endpoints.triggers),
        get(endpoints.slWidth), get(endpoints.rollout),
      ]);
      setAnalysis(a); setTriggers(t); setSlWidth(s); setRollout(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "gagal memuat data keluar");
    } finally {
      setLoading(false);
    }
  }, [market]);

  useEffect(() => { void fetchAll(); }, [fetchAll]);

  const marketNav = (
    <div className="flex flex-wrap gap-1 bg-neutral-100 p-1 rounded-xl w-fit">
      {MARKETS.map(m => {
        const siap = Object.values(m.endpoints).some(Boolean);
        return (
          <button key={m.key} onClick={() => setMarketKey(m.key)}
            className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
              m.key === marketKey ? "bg-white text-neutral-900 shadow-sm"
                                  : "text-neutral-500 hover:text-neutral-700"}`}>
            {m.icon} {m.label}
            {!siap && (
              <span className="ml-1.5 text-[9px] font-bold text-neutral-400">belum ada</span>
            )}
          </button>
        );
      })}
    </div>
  );

  const wrap = (body: React.ReactNode) => (
    <div className="space-y-3">{marketNav}{body}</div>
  );

  if (market.pending && !Object.values(market.endpoints).some(Boolean)) {
    return wrap(
      <div className="bg-white border border-neutral-200 rounded-2xl p-5 text-center">
        <p className="text-sm font-black text-neutral-800">
          {market.icon} MONITOR {market.label} — belum ada ledger keluar
        </p>
        <p className="text-[11px] text-neutral-500 mt-2 leading-relaxed max-w-xl mx-auto">
          {market.pending}
        </p>
      </div>
    );
  }
  if (loading) return wrap(<Empty>Memuat ledger keputusan keluar…</Empty>);
  if (error) return wrap(<Empty>⚠ {error}</Empty>);

  // Saklar belajar berlaku untuk SEMUA sub-tab: selama mati, tak satu pun angka
  // hasil belajar di halaman ini memengaruhi keputusan monitor.
  const banner = rollout?.status === "ok" && (
    <div className={`rounded-xl border p-3 text-[11px] leading-relaxed ${rollout.learning_enabled
      ? "bg-emerald-50 border-emerald-200 text-emerald-800"
      : "bg-neutral-50 border-neutral-200 text-neutral-600"}`}>
      <span className="font-bold">
        {rollout.learning_enabled ? "🟢 Hasil belajar AKTIF" : "⚪ Hasil belajar belum dinyalakan"}
      </span>
      {" — "}{rollout.note}
    </div>
  );

  return wrap(
    <>
      {banner}
      {subTab === "exit_reasons"  && <ExitReasons  data={analysis} market={market} />}
      {subTab === "exit_triggers" && <ExitTriggers data={triggers} market={market} />}
      {subTab === "exit_sl"       && <ExitSlWidth  data={slWidth}  market={market} />}
      {subTab === "exit_rollout"  && <ExitRollout  data={rollout}  market={market} onRefresh={fetchAll} />}
    </>
  );
}

// ── 1· Alasan tutup ───────────────────────────────────────────────────────────

function ExitReasons({ data, market }: { data: AnalysisResponse | null; market: MarketSpec }) {
  if (!data || data.status !== "ok" || !data.n) {
    return <Empty>Ledger keluar masih kosong — belum ada posisi futures yang tertutup.</Empty>;
  }
  const o = data.overall;

  return (
    <div className="space-y-3">
      <Panel
        title="🚪 Keseluruhan"
        sub={`${data.n} penutupan dalam ${data.window_days} hari terakhir. MFE = gerak menguntungkan TERJAUH selama posisi hidup; "prematur" = ditutup sebelum harga sempat bergerak ke mana pun.`}>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <Stat label="Expectancy" value={pct(o?.expectancy_pct, 3)} tone={pnlTone(o?.expectancy_pct)} />
          <Stat label="Win rate" value={o?.win_rate === null ? "—" : `${o?.win_rate}%`} />
          <Stat label="Profit factor" value={num(o?.profit_factor, 3)} />
          <Stat label="MFE median" value={`${num(o?.mfe_atr_median)}× ATR`} />
          <Stat label="Exit prematur" value={frac(o?.premature_frac)} />
        </div>
      </Panel>

      <Panel
        title="Per alasan tutup"
        sub="Alasan mana yang menguntungkan, mana yang justru merugikan.">
        <BucketTable rows={data.by_close_reason ?? []} renderKey={(k) => <ReasonLabel value={k} />} />
      </Panel>

      <Panel title="Per lane" sub="Lane tumbuh dari data — lane baru muncul sendiri di sini.">
        <BucketTable rows={data.by_lane ?? []} renderKey={(k) => <LaneBadge lane={k} market={market} />} />
      </Panel>

      <Panel title="Per regime pasar">
        <BucketTable rows={data.by_regime ?? []} renderKey={(k) => <span className="text-[11px]">{k}</span>} />
      </Panel>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl bg-neutral-50 border border-neutral-200 p-2.5">
      <p className="text-[10px] text-neutral-500 font-semibold">{label}</p>
      <p className={`text-sm font-black mt-0.5 ${tone ?? "text-neutral-800"}`}>{value}</p>
    </div>
  );
}

function BucketTable({ rows, renderKey }: {
  rows: Bucket[]; renderKey: (k: string) => React.ReactNode;
}) {
  if (!rows.length) return <Empty>Belum ada data.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[10px] uppercase text-neutral-400 border-b border-neutral-200">
            <th className="text-left py-1.5 font-semibold">Kunci</th>
            <th className="text-right font-semibold">n</th>
            <th className="text-right font-semibold">Expectancy</th>
            <th className="text-right font-semibold">Win rate</th>
            <th className="text-right font-semibold">MFE/ATR</th>
            <th className="text-right font-semibold">Tahan</th>
            <th className="text-right font-semibold">Prematur</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-neutral-100 last:border-0">
              <td className="py-1.5">{renderKey(r.key ?? "—")}</td>
              <td className="text-right tabular-nums">{r.n}</td>
              <td className={`text-right tabular-nums font-bold ${pnlTone(r.expectancy_pct)}`}>
                {pct(r.expectancy_pct, 3)}
              </td>
              <td className="text-right tabular-nums">{r.win_rate === null ? "—" : `${r.win_rate}%`}</td>
              <td className="text-right tabular-nums">{num(r.mfe_atr_median)}</td>
              <td className="text-right tabular-nums">
                {r.held_hours_median === null ? "—" : `${r.held_hours_median.toFixed(1)}j`}
              </td>
              <td className="text-right tabular-nums">{frac(r.premature_frac)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── 2· Pemicu keluar dini ─────────────────────────────────────────────────────

function ExitTriggers({ data, market }: { data: TriggersResponse | null; market: MarketSpec }) {
  if (!data || data.status !== "ok") {
    return <Empty>Belum bisa menilai pemicu keluar dini.</Empty>;
  }
  const rows = data.triggers ?? [];
  if (!rows.length) {
    return <Empty>Belum ada satu pun penutupan lewat pemicu dini pada jendela ini.</Empty>;
  }

  return (
    <Panel
      title="⚡ Pemicu keluar dini — menyelamatkan atau merugikan?"
      sub={
        "Pemicu dini menutup posisi SEBELUM SL tersentuh. Ukurannya bukan untung/rugi mentah, " +
        "melainkan perbandingan terhadap alternatifnya: kalau posisi dibiarkan, kerugian " +
        "terburuknya adalah jarak SL. \"Gap\" = jarak SL ÷ titik potong — gap kecil berarti " +
        "pemicu nyaris berimpit dengan SL, jadi memotong dini hampir tak menyelamatkan apa pun."
      }>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase text-neutral-400 border-b border-neutral-200">
              <th className="text-left py-1.5 font-semibold">Lane</th>
              <th className="text-left font-semibold">Pemicu</th>
              <th className="text-right font-semibold">n</th>
              <th className="text-right font-semibold">Win rate</th>
              <th className="text-right font-semibold">Expectancy</th>
              <th className="text-right font-semibold">Realisasi</th>
              <th className="text-right font-semibold">Jarak SL</th>
              <th className="text-right font-semibold">Gap</th>
              <th className="text-right font-semibold">Tanpa selamat</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const cukup = data.min_samples === undefined || r.n >= data.min_samples;
              return (
                <tr key={`${r.lane}-${r.trigger}`} className="border-b border-neutral-100 last:border-0">
                  <td className="py-1.5"><LaneBadge lane={r.lane} market={market} /></td>
                  <td className="font-mono text-[11px]">
                    {r.trigger}
                    {r.from_backfill && (
                      <span className="ml-1.5 text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-200"
                        title="Seluruh baris kelompok ini berasal dari pemulihan riwayat">
                        dipulihkan
                      </span>
                    )}
                  </td>
                  <td className="text-right tabular-nums">
                    {r.n}
                    {!cukup && (
                      <span className="ml-1 text-[9px] text-neutral-400" title={`Belum cukup untuk menghasilkan usulan (butuh ${data.min_samples})`}>
                        /{data.min_samples}
                      </span>
                    )}
                  </td>
                  <td className={`text-right tabular-nums font-bold ${r.win_rate === 0 ? "text-rose-600" : ""}`}>
                    {r.win_rate === null ? "—" : `${r.win_rate}%`}
                  </td>
                  <td className={`text-right tabular-nums font-bold ${pnlTone(r.expectancy_pct)}`}>
                    {pct(r.expectancy_pct, 3)}
                  </td>
                  <td className="text-right tabular-nums">{num(r.realized_atr_median)}×</td>
                  <td className="text-right tabular-nums">{num(r.sl_dist_atr_median)}×</td>
                  <td className={`text-right tabular-nums font-bold ${
                    r.sl_gap_median !== null && r.sl_gap_median < SOROT.gapSempit ? "text-rose-600" : "text-neutral-700"}`}>
                    {num(r.sl_gap_median)}
                  </td>
                  <td className={`text-right tabular-nums ${
                    r.no_saving_frac !== null && r.no_saving_frac > 0 ? "text-rose-600 font-bold" : ""}`}>
                    {frac(r.no_saving_frac)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-neutral-400 mt-2.5 leading-relaxed">
        Baris ber-<span className="font-bold">gap kecil</span> dan{" "}
        <span className="font-bold">win rate 0%</span> adalah kandidat untuk dipadamkan di lane
        tersebut — tanpa menyentuh lane yang gap-nya lebar, di mana pemicu yang sama justru berguna.
        Usulan otomatis baru muncul setelah sampelnya mencukupi.
      </p>
    </Panel>
  );
}

// ── 3· Lebar SL ───────────────────────────────────────────────────────────────

function ExitSlWidth({ data, market }: { data: SlWidthResponse | null; market: MarketSpec }) {
  if (!data || data.status !== "ok" || !data.lanes?.length) {
    return <Empty>Belum cukup data untuk membedah lebar SL.</Empty>;
  }
  const terhadapHarga = data.verdict === "sl_disusun_terhadap_harga";

  return (
    <div className="space-y-3">
      <Panel title="📏 Lebar SL disusun terhadap apa?" sub={data.note}>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          <Stat label="Sebaran SL (harga %)" value={num(data.cv_sl_pct_all, 3)} />
          <Stat label="Sebaran SL (× ATR)" value={num(data.cv_sl_atr_all, 3)} />
          <Stat
            label="Kesimpulan"
            value={terhadapHarga ? "terhadap HARGA" : "terhadap VOLATILITAS"}
            tone={terhadapHarga ? "text-amber-600" : "text-emerald-600"}
          />
        </div>
        {terhadapHarga && (
          <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-xl p-2.5 mt-2.5 leading-relaxed">
            Sebaran dalam harga% lebih rapat daripada dalam kelipatan ATR — artinya lebar SL
            sebenarnya ditentukan harga, bukan volatilitas koin. Perbedaan kelipatan ATR antar
            lane di bawah ini adalah <span className="font-bold">efek samping</span> dari koin yang
            diperdagangkan tiap lane, bukan keputusan desain.
          </p>
        )}
      </Panel>

      <Panel
        title="Per lane"
        sub={'"Mentok plafon" = porsi posisi yang SL-nya dibatasi plafon, bukan hasil rumus ATR. Angka tinggi berarti rumus sadar-volatilitas jarang benar-benar berlaku. "SL/MFE" = SL berapa kali lebih jauh daripada gerak untung terjauh yang nyata.'}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase text-neutral-400 border-b border-neutral-200">
                <th className="text-left py-1.5 font-semibold">Lane</th>
                <th className="text-right font-semibold">n</th>
                <th className="text-right font-semibold">ATR</th>
                <th className="text-right font-semibold">SL harga</th>
                <th className="text-right font-semibold">SL/ATR</th>
                <th className="text-right font-semibold">Plafon</th>
                <th className="text-right font-semibold">Mentok</th>
                <th className="text-right font-semibold">SL/MFE</th>
                <th className="text-right font-semibold">Win rate</th>
              </tr>
            </thead>
            <tbody>
              {data.lanes.map((l) => (
                <tr key={l.lane} className="border-b border-neutral-100 last:border-0">
                  <td className="py-1.5"><LaneBadge lane={l.lane} market={market} /></td>
                  <td className="text-right tabular-nums">{l.n}</td>
                  <td className="text-right tabular-nums">{pct(l.atr_pct_median)}</td>
                  <td className="text-right tabular-nums">{pct(l.sl_pct_median)}</td>
                  <td className="text-right tabular-nums">{num(l.sl_atr_median)}×</td>
                  <td className="text-right tabular-nums text-neutral-400">{pct(l.configured_max_pct, 1)}</td>
                  <td className={`text-right tabular-nums font-bold ${
                    (l.pinned_at_max_frac ?? 0) >= SOROT.seringMentok ? "text-rose-600" : "text-neutral-700"}`}>
                    {frac(l.pinned_at_max_frac)}
                  </td>
                  <td className={`text-right tabular-nums ${
                    l.sl_vs_mfe !== null && l.sl_vs_mfe >= SOROT.slJauhDariMfe ? "text-amber-600 font-bold" : ""}`}>
                    {num(l.sl_vs_mfe, 2)}×
                  </td>
                  <td className="text-right tabular-nums">{l.win_rate === null ? "—" : `${l.win_rate}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

// ── 4· Penyalaan bertahap ─────────────────────────────────────────────────────

const STAGE_STYLE: Record<string, { label: string; cls: string }> = {
  shadow:      { label: "Bayangan",  cls: "bg-neutral-100 text-neutral-600 border-neutral-200" },
  canary:      { label: "Uji 1 lane", cls: "bg-amber-100 text-amber-700 border-amber-200" },
  active:      { label: "Aktif",     cls: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  rolled_back: { label: "Dibalik",   cls: "bg-rose-100 text-rose-700 border-rose-200" },
};

function StageBadge({ stage }: { stage: string }) {
  const s = STAGE_STYLE[stage] ?? { label: stage, cls: "bg-neutral-100 text-neutral-600 border-neutral-200" };
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${s.cls}`}>{s.label}</span>
  );
}

function ExitRollout({ data, market, onRefresh }: { data: RolloutResponse | null; market: MarketSpec; onRefresh: () => void }) {
  if (!market.endpoints.rollout) {
    return (
      <div className="bg-white border border-neutral-200 rounded-2xl p-5 text-center">
        <p className="text-sm font-black text-neutral-800">
          {market.icon} {market.label} — belum ada parameter keluar yang bisa ditala
        </p>
        <p className="text-[11px] text-neutral-500 mt-2 leading-relaxed max-w-xl mx-auto">
          Tahapan penyalaan menyetel parameter monitor yang sudah terpusat dan
          bisa di-override dari DB. Sisi {market.label} belum punya padanannya,
          jadi halaman ini sengaja kosong — tahapan milik market lain TIDAK
          ditampilkan di sini.
        </p>
      </div>
    );
  }
  if (!data || data.status !== "ok") {
    return <Empty>Tahapan penyalaan belum bisa dibaca.</Empty>;
  }
  const rows = data.rollouts ?? [];

  return (
    <div className="space-y-3">
      <Panel
        title="🚦 Tahapan penyalaan parameter keluar"
        sub={
          "Setiap perubahan parameter keluar melewati tahapan yang sama dengan model sisi masuk: " +
          "bayangan → uji satu lane → aktif, atau dibalik bila memburuk. Baseline direkam SEBELUM " +
          "angka berlaku — tanpa pembanding, \"membaik\" hanya klaim."
        }>
        {/* Gate datang dari API, bukan ditulis di UI — supaya angka di layar tak
            pernah berbeda dari syarat yang benar-benar dipakai mesin. */}
        <div className="flex flex-wrap gap-2">
          {Object.entries(data.gates ?? {}).map(([k, v]) => (
            <span key={k} className="text-[10px] font-mono bg-neutral-50 border border-neutral-200 rounded-lg px-2 py-1 text-neutral-600">
              {k} = <span className="font-bold text-neutral-800">{v}</span>
            </span>
          ))}
          <button onClick={onRefresh}
            className="text-[10px] font-bold bg-neutral-900 text-white rounded-lg px-3 py-1 hover:bg-neutral-700 transition-colors">
            Muat ulang
          </button>
        </div>
      </Panel>

      {rows.length === 0 ? (
        <Empty>
          Belum ada usulan yang masuk antrean penyalaan.
          <br />
          <span className="text-[11px]">
            Usulan muncul setelah sebuah lane punya cukup sampel di ledger keluar.
          </span>
        </Empty>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => (
            <div key={r.id} className="bg-white border border-neutral-200 rounded-2xl p-3.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <StageBadge stage={r.stage} />
                  <LaneBadge lane={r.lane} market={market} />
                  <span className="font-mono text-[11px] text-neutral-500">{r.param}</span>
                </div>
                <span className="text-[11px] font-mono text-neutral-600">
                  {r.previous_value} <span className="text-neutral-400">→</span>{" "}
                  <span className="font-bold text-neutral-900">{r.proposed_value}</span>
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 mt-2.5">
                <MetricPair title="Sebelum (baseline)" m={r.baseline} />
                <MetricPair title="Sesudah (teramati)" m={r.observed} />
              </div>

              {r.reason && (
                <p className="text-[10px] text-neutral-500 mt-2 leading-relaxed">{r.reason}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MetricPair({ title, m }: {
  title: string; m: { n: number; expectancy_pct: number | null; win_rate: number | null };
}) {
  return (
    <div className="rounded-xl bg-neutral-50 border border-neutral-200 p-2.5">
      <p className="text-[10px] text-neutral-500 font-semibold">{title}</p>
      <p className="text-xs mt-1">
        <span className="text-neutral-400">n=</span>
        <span className="font-bold tabular-nums">{m.n}</span>
        <span className="mx-1.5 text-neutral-300">·</span>
        <span className={`font-bold tabular-nums ${pnlTone(m.expectancy_pct)}`}>
          {pct(m.expectancy_pct, 3)}
        </span>
        <span className="mx-1.5 text-neutral-300">·</span>
        <span className="tabular-nums">{m.win_rate === null ? "—" : `${m.win_rate}%`}</span>
      </p>
    </div>
  );
}
