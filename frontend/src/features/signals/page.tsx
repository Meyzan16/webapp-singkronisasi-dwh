"use client";
import { useCallback, useEffect, useMemo, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentStat {
  label:       string;
  win_rate:    number;
  total:       number;
  wins:        number;
  avg_pnl_pct: number;
  weight:      number;
}

interface SignalRow {
  signal_key:    string;
  agents:        Record<string, AgentStat>;
  best_win_rate: number;
  best_avg_pnl:  number;
  total_trades:  number;
  cross_weight:  number | null;
}

interface CrossSignalRow {
  signal_key:      string;
  cross_weight:    number;
  cross_win_rate:  number;
  cross_total:     number;
  avg_pnl_pct:     number;
  agent_count:     number;
  agents:          Record<string, { label: string; win_rate: number; total: number; weight: number }>;
  reliability:     "high" | "medium" | "low";
}

interface UpdaterState {
  futures: { last_run?: number; last_error?: string; cached_agents?: string[] };
  spot:    { last_run?: number; last_error?: string; last_count?: number };
  cross:   { last_run?: number; last_error?: string; cached_keys?: number };
}

interface PerformanceResponse {
  signals: SignalRow[];
  meta:    { total: number; shown: number };
}

interface CrossResponse {
  signals: CrossSignalRow[];
  meta:    { total: number };
}

interface RegimeRow {
  signal_key:    string;
  regimes:       Record<string, number | null>;
  max_deviation: number;
}

interface RegimeResponse {
  signals: RegimeRow[];
  regimes: string[];
}

interface CatalogAgent {
  agent:   string;
  label:   string;
  max_pts: number;
  file:    string;
  fn:      string;
}

interface CatalogEntry {
  label:                string;
  category:             string;
  description:          string;
  agents:               CatalogAgent[];
  score_impact_formula: string;
}

interface CatalogResponse {
  catalog:    Record<string, CatalogEntry>;
  categories: string[];
  total:      number;
}

interface RejectionRow {
  id: number; symbol: string; agent: string; direction: string;
  score: number; threshold: number; regime: string;
  weak_signals: string[] | null;  // API returns array, not string
  rejected_at: number;
}

interface PredictiveHitRow {
  agent: string; direction: string; total: number;
  hit_rate_4h: number; hit_rate_24h: number;
  avg_move_4h: number; avg_move_24h: number;
}

interface LaneHealth {
  lane: string; agent: string; label: string;
  paused: boolean; pause_until?: number;
  wr: number; trades: number;
}

interface AgentHealthData {
  scan: {
    running: boolean; cycle_count: number; last_scan_ts?: number;
    next_scan_in_min?: number; last_error?: string; interval_minutes: number;
  };
  gate: {
    active: boolean; gate_type: string; reason: string;
    drawdown_pct?: number; dd_threshold?: number;
    rar?: number; n_trades: number; stale: boolean;
  };
  lanes: LaneHealth[];
  learning: {
    cached_keys: number; cached_agents: string[];
    blacklisted_count: number; blacklisted_coins: string[];
    bl_directional: { symbol: string; direction: string }[];
    last_run?: number; last_error?: string;
  };
}

interface AdaptiveEngineData {
  engine_status: "degraded" | "collecting" | "shadow" | "canary" | "champion";
  decision_ledger: {
    total: number;
    actions: Record<string, number>;
    outcomes: Record<string, number>;
    due_24h: number;
    labelled_24h: number;
    outcome_completeness_pct: number;
    quality: { duplicate_keys: number; missing_snapshots: number; future_events: number; invalid_closes: number };
  };
  training: { mature_feature_samples: number; required_samples: number; progress_pct: number };
  models: Array<{
    version: string; status: string; trained_at: number; promoted_at?: number;
    training_n: number; promotion_eligible: boolean;
    test?: { n?: number; brier?: number; selected_expectancy_pct?: number; selected_profit_factor?: number };
  }>;
  walkforward: {
    status: string; n?: number; best_threshold?: number; promotion_eligible?: boolean;
    test?: { n?: number; expectancy_pct?: number; profit_factor?: number; max_drawdown_pct?: number };
  };
  onchain: { mode?: string; configured?: boolean; cache_entries?: number; mapping_version?: string; mapped_assets?: number; error?: string };
  weights: { last_run?: number; last_error?: string; last_count?: number };
  gates: Record<string, boolean>;
  updated_at: number;
}

// PLAN_ADAPTIVE_LEARNING_FUTURES_10X F6 — panel engine futures (paralel SPOT)
interface FuturesAdaptiveEngineData {
  market: "futures";
  engine_status: "degraded" | "collecting" | "ready_to_train" | "shadow" | "canary" | "champion";
  learning_status: "warming" | "active" | "degraded";
  decision_ledger: {
    total: number; opened: number;
    actions: Record<string, number>;
    outcomes: Record<string, number>;
    reasons: Record<string, number>;
    realized_linked: number;
    due_24h: number; labelled_24h: number;
    outcome_completeness_pct: number;
    quality: { duplicate_keys: number; missing_snapshots: number; future_events: number; invalid_closes: number };
    oldest_scan_ts: number | null; latest_scan_ts: number | null;
  };
  training: { mature_feature_samples: number; required_samples: number; progress_pct: number };
  models: Array<{
    version: string; status: string; trained_at: number; training_n: number;
    promotion_eligible: boolean; label_horizon: string;
    test?: { n?: number; brier?: number; selected_expectancy_pct?: number; selected_profit_factor?: number };
  }>;
  walkforward?: {
    status: string; best_threshold?: number; promotion_eligible?: boolean;
    test?: { n?: number; expectancy_pct?: number; profit_factor?: number; max_drawdown_pct?: number };
    test_stressed_1_5x?: { n?: number; expectancy_pct?: number; profit_factor?: number };
  };
  phases: Record<string, boolean>;
  gates: Record<string, boolean>;
  updated_at: number;
}

interface ReviewAdjustment {
  agent: string; signal_key: string; n: number;
  hit_rate_4h: number; old_weight: number; new_weight: number;
}

interface ReviewData {
  ran_at: number | null;
  resolved_rows: number;
  adjustments: ReviewAdjustment[];
}

type SubTab = "overview" | "adaptive" | "spot" | "futures" | "cross" | "improvements" | "regime" | "formulas" | "rejections" | "predictive";
type SortBy = "win_rate" | "avg_pnl_pct" | "total_count" | "weight";

// ── Navigasi 2-level: 4 seksi ber-scope (refactor UX — dulu 9 tab flat) ────────
type Section = "overview" | "engine" | "signals" | "analysis";

const SECTION_OF: Record<SubTab, Section> = {
  overview: "overview",
  adaptive: "engine",
  spot: "signals", futures: "signals", cross: "signals",
  improvements: "analysis",
  regime: "analysis", formulas: "analysis", rejections: "analysis", predictive: "analysis",
};

// Tab default saat sebuah seksi dibuka
const SECTION_DEFAULT: Record<Section, SubTab> = {
  overview: "overview", engine: "adaptive", signals: "spot", analysis: "improvements",
};

const SECTIONS: { key: Section; icon: string; label: string; desc: string }[] = [
  { key: "overview", icon: "📊", label: "Overview",  desc: "Ringkasan cepat: kesehatan agen & mesin" },
  { key: "engine",   icon: "🧠", label: "Engine",    desc: "Mesin belajar adaptif SPOT & Futures" },
  { key: "signals",  icon: "🎯", label: "Signals",   desc: "Bobot sinyal yang dipelajari per market" },
  { key: "analysis", icon: "🔬", label: "Analysis",  desc: "Perbaikan live, regime, rumus, rejections, prediksi" },
];

// Sub-tab per seksi (hanya Signals & Analysis punya inner nav)
const SUBTABS_OF: Record<Section, { key: SubTab; label: string }[]> = {
  overview: [],
  engine:   [],
  signals:  [
    { key: "spot",    label: "🎯 SPOT" },
    { key: "futures", label: "⚡ Futures" },
    { key: "cross",   label: "🔗 Cross-Agent" },
  ],
  analysis: [
    { key: "improvements", label: "🔧 Perbaikan" },
    { key: "regime",     label: "🌡 Regime" },
    { key: "formulas",   label: "🔬 Formulas" },
    { key: "rejections", label: "🚫 Rejections" },
    { key: "predictive", label: "🔮 Predictive" },
  ],
};

const AGENT_TABS = [
  { key: "opportunity_spot", label: "SPOT",          color: "text-teal-700",   bg: "bg-teal-100 border-teal-200" },
  { key: "futures_agent1",   label: "Pre-Gainer",    color: "text-blue-700",   bg: "bg-blue-100 border-blue-200" },
  { key: "futures_agent2",   label: "Accumulation",  color: "text-purple-700", bg: "bg-purple-100 border-purple-200" },
  { key: "futures_agent3",   label: "Momentum",      color: "text-orange-700", bg: "bg-orange-100 border-orange-200" },
];

// ── Lapisan awam (PLAN_UX_AWAM_SIGNAL_PERFORMANCE) ────────────────────────────
// Terjemahan Bahasa Indonesia polos di atas data live — info teknis tetap ada.

const REASON_LABELS: Record<string, string> = {
  below_auto_threshold:   "Skor di bawah ambang minimal",
  dedup_lost:             "Kalah prioritas dari kandidat lain",
  volatile_regime_skip:   "Market terlalu bergejolak",
  already_open:           "Posisi coin ini sudah terbuka",
  sl_cooldown:            "Jeda setelah kena stop-loss",
  profit_lock_skip:       "Profit harian sudah dikunci",
  direction_cap:          "Batas posisi searah sudah penuh",
  bm_daily_budget:        "Budget harian BigMover habis",
  bm_daily_sl_stop:       "BigMover berhenti (SL harian)",
  breadth_fade_skip:      "Kondisi pasar sedang melemah",
  funding_hard_skip:      "Biaya funding terlalu mahal",
  bm_lane_full:           "Slot BigMover penuh",
  lane_quota_full:        "Kuota lane penuh",
  lane_paused:            "Lane sedang dijeda",
  funding_flip:           "Arah biaya funding berbalik",
  cost_floor_skip:        "Potensi profit tak menutup biaya",
  sizing_blocked:         "Ukuran posisi tak memenuhi syarat",
  min_notional_skip:      "Nilai order di bawah minimum exchange",
  risk_gate_blocked:      "Gerbang risiko sedang aktif",
  daily_gate_blocked:     "Batas kerugian harian tercapai",
  consec_sl_global_pause: "Pause global (SL beruntun)",
};

const ENGINE_STATUS_PLAIN: Record<string, string> = {
  degraded:       "Ada masalah pada data/mesin — perlu dicek. Trading tetap memakai aturan lama yang aman.",
  collecting:     "Mesin sedang mengumpulkan data keputusan. Model AI belum dilatih — tahap awal yang normal.",
  ready_to_train: "Data sudah cukup — model AI akan dilatih otomatis pada siklus berikutnya.",
  shadow:         "Model AI sudah dilatih dan sedang MENGAMATI saja: ia membuat prediksi diam-diam, tapi TIDAK memengaruhi keputusan trading sampai lulus semua uji.",
  canary:         "Model AI sedang uji coba terbatas (canary). Kalau hasilnya buruk, otomatis dibatalkan dan kembali ke aturan lama.",
  champion:       "Model AI sudah lulus semua uji dan kini aktif membantu keputusan trading.",
};

const LEARNING_STATUS_PLAIN: Record<string, string> = {
  warming:  "pembelajaran masih pemanasan — belum ikut memveto trade",
  active:   "pembelajaran aktif — sinyal yang terbukti jelek otomatis diveto",
  degraded: "pembelajaran bermasalah — veto dimatikan sementara",
};

const GLOSSARY: { term: string; plain: string }[] = [
  { term: "Shadow → Canary → Champion", plain: "Tahapan hidup model AI: mengamati saja → uji coba terbatas → dipakai sungguhan. Model tidak boleh loncat tahap." },
  { term: "Mature samples",             plain: "Jumlah keputusan yang hasil akhirnya sudah diketahui — ini bahan belajar model. Minimal 60 sebelum training." },
  { term: "Brier score",                plain: "Ukuran akurasi prediksi: 0 = sempurna, makin kecil makin baik." },
  { term: "Expectancy",                 plain: "Rata-rata untung/rugi per trade setelah SEMUA biaya (fee, slippage, funding). Harus positif." },
  { term: "Profit Factor (PF)",         plain: "Total untung dibagi total rugi. Di atas 1.5 dianggap sehat." },
  { term: "OOS (out-of-sample)",        plain: "Model diuji pada data yang belum pernah ia lihat — mencegah nilai bagus palsu karena hafalan." },
  { term: "Veto-only",                  plain: "Pembelajaran hanya boleh MENCEGAH trade yang terbukti jelek — tidak pernah memaksa membuka trade." },
  { term: "Decision ledger",            plain: "Buku catatan permanen: setiap kandidat trade dicatat lengkap dengan alasan dibuka/ditolak dan hasil akhirnya." },
];

function GlossaryBox() {
  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">📖 Kamus Istilah (untuk non-teknis)</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
        {GLOSSARY.map(g => (
          <div key={g.term} className="text-[11px] leading-relaxed">
            <span className="font-bold text-neutral-700">{g.term}</span>
            <span className="text-neutral-500"> — {g.plain}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PlainSummaryBanner({ health, futures }: {
  health:  AgentHealthData | null;
  futures: FuturesAdaptiveEngineData | null;
}) {
  const running     = health?.scan.running ?? false;
  const lastScan    = health?.scan.last_scan_ts;
  const lastScanStr = lastScan ? new Date(lastScan * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }) : "—";
  const learnedKeys = health?.learning.cached_keys ?? 0;
  const decisions   = futures?.decision_ledger.total ?? 0;
  const opened      = futures?.decision_ledger.opened ?? 0;
  const learnPlain  = futures ? (LEARNING_STATUS_PLAIN[futures.learning_status] ?? futures.learning_status) : "belum ada data";

  const cards = [
    {
      q: "Apakah sistem bekerja?",
      ok: running,
      a: running
        ? `Ya. Scanner memeriksa pasar setiap ${health?.scan.interval_minutes ?? "—"} menit tanpa henti (sudah ${health?.scan.cycle_count ?? "—"} putaran, terakhir ${lastScanStr}).`
        : "Tidak — scanner sedang berhenti. Backend perlu dicek.",
    },
    {
      q: "Apa yang sudah dipelajari?",
      ok: learnedKeys > 0,
      a: `Sistem sudah menilai ${learnedKeys} jenis sinyal dari hasil trade nyata dan mencatat ${decisions.toLocaleString("id-ID")} keputusan futures lengkap dengan alasannya. Saat ini ${learnPlain}.`,
    },
    {
      q: "Apa output-nya?",
      ok: opened > 0,
      a: `Sinyal entry lengkap (harga masuk, stop-loss, target profit) yang otomatis jadi paper trade — ${opened} dibuka dari catatan terakhir. Hasil menang/kalahnya bisa dilihat di halaman History.`,
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {cards.map(c => (
        <div key={c.q} className={`rounded-2xl border p-4 ${c.ok ? "bg-green-50 border-green-200" : "bg-amber-50 border-amber-200"}`}>
          <p className={`text-xs font-black mb-1.5 ${c.ok ? "text-green-800" : "text-amber-800"}`}>
            {c.ok ? "✅" : "⏳"} {c.q}
          </p>
          <p className="text-[11px] leading-relaxed text-neutral-600">{c.a}</p>
        </div>
      ))}
    </div>
  );
}

// ── PipelineLive (P1) — alur kerja SPOT & FUTURES tahap demi tahap, live ──────

type StageState = "live" | "current" | "wait";

interface PipelineStageDef {
  icon: string;
  label: string;
  sub: string;
  state: StageState;
}

const STAGE_CLS: Record<StageState, string> = {
  live:    "bg-green-50 border-green-200 text-green-700",
  current: "bg-blue-50 border-blue-400 text-blue-700 ring-2 ring-blue-200",
  wait:    "bg-neutral-50 border-neutral-200 text-neutral-400",
};

function PipelineRow({ title, badge, stages }: { title: string; badge: string; stages: PipelineStageDef[] }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <p className="text-xs font-black text-neutral-700">{title}</p>
        <span className="text-[9px] font-bold bg-neutral-100 text-neutral-500 border border-neutral-200 rounded-full px-2 py-0.5 capitalize">{badge}</span>
      </div>
      <div className="flex flex-wrap items-stretch gap-1">
        {stages.map((s, i) => (
          <div key={s.label} className="flex items-center gap-1">
            <div className={`rounded-lg border px-2 py-1.5 min-w-[86px] ${STAGE_CLS[s.state]}`}>
              <p className="text-[10px] font-black leading-tight">
                {s.state === "live" ? "✓" : s.state === "current" ? "●" : "○"} {s.icon} {s.label}
              </p>
              <p className="text-[9px] mt-0.5 leading-tight opacity-80">{s.sub}</p>
            </div>
            {i < stages.length - 1 && <span className="text-neutral-300 text-xs font-bold">→</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function PipelineLive({ spot, futures, health, updater }: {
  spot:    AdaptiveEngineData | null;
  futures: FuturesAdaptiveEngineData | null;
  health:  AgentHealthData | null;
  updater: UpdaterState | null;
}) {
  const fmtT = (ts?: number | null) => ts ? new Date(ts * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }) : "—";
  // Posisi model dalam lifecycle: sebelum shadow = belum ada model jalan
  const lifeIdx = (st?: string) => st === "shadow" ? 0 : st === "canary" ? 1 : st === "champion" ? 2 : -1;

  const lifecycleStages = (st: string | undefined): PipelineStageDef[] => {
    const cur = lifeIdx(st);
    return [
      { icon: "👁", label: "Shadow",   sub: "model mengamati saja" },
      { icon: "🐤", label: "Canary",   sub: "uji coba terbatas" },
      { icon: "🏆", label: "Champion", sub: "dipakai sungguhan" },
    ].map((s, i) => ({ ...s, state: (i === cur ? "current" : i < cur ? "live" : "wait") as StageState }));
  };

  const spotStages: PipelineStageDef[] = spot ? [
    { icon: "🔍", label: "Scan",           sub: "pasar spot, rutin",                                                        state: "live" },
    { icon: "🧾", label: "Catat Keputusan", sub: `${spot.decision_ledger.total.toLocaleString("id-ID")} keputusan`,          state: spot.decision_ledger.total > 0 ? "live" : "wait" },
    { icon: "⏱", label: "Cek Hasil",       sub: `${spot.decision_ledger.outcome_completeness_pct.toFixed(0)}% terlabel`,    state: spot.decision_ledger.labelled_24h > 0 ? "live" : "wait" },
    { icon: "⚖️", label: "Belajar Bobot",   sub: updater?.spot?.last_count != null ? `${updater.spot.last_count} keys · ${fmtT(updater.spot.last_run)}` : "menunggu", state: updater?.spot?.last_run ? "live" : "wait" },
    { icon: "🤖", label: "Latih Model",     sub: spot.models.length ? `${spot.models[0].training_n} sampel` : `${spot.training.progress_pct.toFixed(0)}% data`, state: spot.models.length ? "live" : "wait" },
    ...lifecycleStages(spot.engine_status),
  ] : [];

  const futStages: PipelineStageDef[] = futures ? [
    { icon: "🔍", label: "Scan",           sub: health ? `tiap ${health.scan.interval_minutes} mnt · #${health.scan.cycle_count}` : "—", state: health?.scan.running ? "live" : "wait" },
    { icon: "🧾", label: "Catat Keputusan", sub: `${futures.decision_ledger.total.toLocaleString("id-ID")} · ${futures.decision_ledger.opened} dibuka`, state: futures.decision_ledger.total > 0 ? "live" : "wait" },
    { icon: "⏱", label: "Cek Hasil",       sub: `${futures.decision_ledger.outcome_completeness_pct.toFixed(0)}% terlabel (NET biaya)`, state: futures.decision_ledger.labelled_24h > 0 ? "live" : "wait" },
    { icon: "⚖️", label: "Belajar Bobot",   sub: `${health?.learning.cached_keys ?? 0} sinyal · ${futures.learning_status}`, state: futures.learning_status === "active" ? "live" : futures.learning_status === "warming" ? "current" : "wait" },
    { icon: "🤖", label: "Latih Model",     sub: futures.models.length ? `${futures.models[0].training_n} sampel` : `${futures.training.progress_pct.toFixed(0)}% data`, state: futures.models.length ? "live" : "wait" },
    ...lifecycleStages(futures.engine_status),
  ] : [];

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4 space-y-4">
      <div>
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">🔄 Pipeline Live — cara sistem bekerja, tahap demi tahap</p>
        <p className="text-[10px] text-neutral-400 mt-0.5">
          ✓ hijau = tahap berjalan terus-menerus · ● biru = posisi saat ini · ○ abu = belum sampai.
          Model AI hanya boleh maju satu tahap setelah lulus uji.
        </p>
      </div>
      {spotStages.length > 0
        ? <PipelineRow title="🎯 SPOT" badge={spot?.engine_status ?? "—"} stages={spotStages} />
        : <p className="text-[11px] text-neutral-400">Pipeline SPOT belum tersedia.</p>}
      {futStages.length > 0
        ? <PipelineRow title="⚡ FUTURES" badge={futures?.engine_status ?? "—"} stages={futStages} />
        : <p className="text-[11px] text-neutral-400">Pipeline FUTURES belum tersedia.</p>}
    </div>
  );
}

// ── ImprovementsTab (P4) — apa yang sedang diperbaiki sistem, live ────────────

interface MoverRow {
  signal_key: string;
  agentLabel: string;
  stat: AgentStat;
}

const AGENT_LABEL: Record<string, string> = {
  opportunity_spot: "SPOT", futures_agent1: "Pre-Gainer",
  futures_agent2: "Accumulation", futures_agent3: "Momentum",
  futures_agent_bigmover: "BigMover",
};

function MoverList({ title, rows, tone, emptyText, catalog }: {
  title: string;
  rows: MoverRow[];
  tone: "up" | "down" | "veto";
  emptyText: string;
  catalog: CatalogResponse | null;
}) {
  const toneCls = tone === "up" ? "text-green-700" : tone === "down" ? "text-amber-700" : "text-red-700";
  return (
    <div className="rounded-xl border border-neutral-200 p-3">
      <p className={`text-[10px] font-bold uppercase tracking-wider mb-2 ${toneCls}`}>{title}</p>
      {rows.length === 0 ? (
        <p className="text-[11px] text-neutral-400">{emptyText}</p>
      ) : (
        <div className="space-y-1.5">
          {rows.map(r => (
            <div key={`${r.signal_key}-${r.agentLabel}`} className="flex items-center justify-between gap-2 text-[11px]">
              <div className="min-w-0">
                <p className="font-semibold text-neutral-700 truncate">
                  {catalog?.catalog?.[r.signal_key]?.label ?? r.signal_key.replace(/_/g, " ")}
                </p>
                <p className="text-[9px] text-neutral-400">{r.agentLabel} · WR {r.stat.win_rate.toFixed(0)}% · {r.stat.total} trades</p>
              </div>
              <span className={`font-black tabular-nums shrink-0 ${toneCls}`}>×{r.stat.weight.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ImprovementsTab({ weightPerf, health, futures, review, catalog }: {
  weightPerf: PerformanceResponse | null;
  health:     AgentHealthData | null;
  futures:    FuturesAdaptiveEngineData | null;
  review:     ReviewData | null;
  catalog:    CatalogResponse | null;
}) {
  const { spotUp, spotDown, futUp, futDown, futVeto } = useMemo(() => {
    const spot: MoverRow[] = [];
    const fut:  MoverRow[] = [];
    for (const s of weightPerf?.signals ?? []) {
      for (const [agentKey, stat] of Object.entries(s.agents)) {
        const row = { signal_key: s.signal_key, agentLabel: AGENT_LABEL[agentKey] ?? agentKey, stat: { ...stat, label: agentKey } };
        // cross_agent bukan market — tampil di Signals→Cross-Agent, bukan di sini
        if (agentKey === "opportunity_spot") spot.push(row);
        else if (agentKey.startsWith("futures_")) fut.push(row);
      }
    }
    const byW  = (dir: 1 | -1) => (a: MoverRow, b: MoverRow) => dir * (b.stat.weight - a.stat.weight);
    return {
      spotUp:   spot.filter(r => r.stat.weight >= 1.05).sort(byW(1)).slice(0, 6),
      spotDown: spot.filter(r => r.stat.weight <= 0.95).sort(byW(-1)).slice(0, 6),
      futUp:    fut.filter(r => r.stat.weight >= 1.05).sort(byW(1)).slice(0, 6),
      futDown:  fut.filter(r => r.stat.weight <= 0.95 && r.stat.weight >= 0.8).sort(byW(-1)).slice(0, 6),
      futVeto:  fut.filter(r => r.stat.weight < 0.8 && r.stat.total >= 10).sort(byW(-1)).slice(0, 6),
    };
  }, [weightPerf]);

  if (!weightPerf) {
    return (
      <div className="flex items-center justify-center py-16 text-neutral-400 gap-2">
        <div className="w-4 h-4 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
        Memuat data perbaikan...
      </div>
    );
  }

  const vetoActive = futures?.learning_status === "active";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* SPOT column */}
        <div className="space-y-3">
          <p className="text-sm font-black text-neutral-800">🎯 SPOT</p>
          <MoverList title="⬆ Bobot dinaikkan — sinyal terbukti profit, pengaruhnya diperbesar"
            rows={spotUp} tone="up" emptyText="Belum ada sinyal yang naik bobot." catalog={catalog} />
          <MoverList title="⬇ Bobot diturunkan — sering rugi, pengaruhnya dikurangi"
            rows={spotDown} tone="down" emptyText="Belum ada sinyal yang turun bobot." catalog={catalog} />
        </div>

        {/* FUTURES column */}
        <div className="space-y-3">
          <p className="text-sm font-black text-neutral-800">⚡ FUTURES</p>
          <MoverList title="⬆ Bobot dinaikkan — sinyal terbukti profit, pengaruhnya diperbesar"
            rows={futUp} tone="up" emptyText="Belum ada sinyal yang naik bobot." catalog={catalog} />
          <MoverList title="⬇ Bobot diturunkan — sering rugi, pengaruhnya dikurangi"
            rows={futDown} tone="down" emptyText="Belum ada sinyal yang turun bobot." catalog={catalog} />
          <MoverList
            title={`⛔ Kandidat veto (bobot <0.8, ≥10 trades) — ${vetoActive ? "trade dengan sinyal ini otomatis DITOLAK" : "veto belum aktif (masih pemanasan)"}`}
            rows={futVeto} tone="veto" emptyText="Tidak ada sinyal yang cukup buruk untuk diveto." catalog={catalog} />

          {/* Blacklist + lane pause dari health */}
          {health && (health.learning.blacklisted_coins.length > 0 || health.lanes.some(l => l.paused)) && (
            <div className="rounded-xl border border-orange-200 bg-orange-50 p-3 space-y-2">
              <p className="text-[10px] font-bold uppercase tracking-wider text-orange-700">🚧 Pengamanan aktif sekarang</p>
              {health.learning.blacklisted_coins.length > 0 && (
                <p className="text-[11px] text-neutral-600">
                  Koin di-blacklist 24 jam (3× stop-loss beruntun):{" "}
                  <span className="font-bold text-orange-700">{health.learning.blacklisted_coins.map(c => c.replace("USDT", "")).join(", ")}</span>
                </p>
              )}
              {health.lanes.filter(l => l.paused).map(l => (
                <p key={l.lane} className="text-[11px] text-neutral-600">
                  Lane <span className="font-bold text-orange-700">{l.label}</span> dijeda sementara karena performa buruk
                  {l.pause_until ? ` (lanjut ${new Date(l.pause_until * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })})` : ""}.
                </p>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Review mingguan */}
      <div className="rounded-xl border border-neutral-200 bg-white p-4">
        <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">📅 Review Mingguan Otomatis (Senin 00:10 UTC)</p>
        {review?.ran_at ? (
          <div className="space-y-1.5">
            <p className="text-[11px] text-neutral-500">
              Terakhir jalan {new Date(review.ran_at * 1000).toLocaleString("id-ID")} · {review.resolved_rows} prediksi dianalisis ·{" "}
              {review.adjustments.length} bobot disesuaikan:
            </p>
            {review.adjustments.slice(0, 10).map(a => (
              <div key={`${a.agent}-${a.signal_key}`} className="flex items-center justify-between text-[11px]">
                <span className="text-neutral-600 truncate">{a.signal_key.replace(/_/g, " ")} <span className="text-neutral-400">({AGENT_LABEL[a.agent] ?? a.agent} · hit {a.hit_rate_4h}% · n={a.n})</span></span>
                <span className={`font-bold tabular-nums shrink-0 ${a.new_weight > a.old_weight ? "text-green-600" : "text-amber-600"}`}>
                  ×{a.old_weight.toFixed(2)} → ×{a.new_weight.toFixed(2)}
                </span>
              </div>
            ))}
            {review.adjustments.length === 0 && <p className="text-[11px] text-neutral-400">Tidak ada bobot yang perlu disesuaikan minggu ini.</p>}
          </div>
        ) : (
          <p className="text-[11px] text-neutral-400">
            Belum pernah jalan — review pertama otomatis Senin depan. Selain review mingguan ini,
            bobot di atas tetap diperbarui otomatis setiap ada trade yang selesai.
          </p>
        )}
      </div>
    </div>
  );
}

// ── Small components ──────────────────────────────────────────────────────────

function WeightBar({ weight }: { weight: number }) {
  const pct = Math.round(((weight - 0.7) / (1.5 - 0.7)) * 100);
  const cls = weight >= 1.3 ? "bg-green-500" : weight >= 1.1 ? "bg-teal-400" : weight >= 0.9 ? "bg-neutral-300" : "bg-red-400";
  const txt = weight >= 1.3 ? "text-green-700" : weight >= 1.1 ? "text-teal-700" : weight >= 0.9 ? "text-neutral-500" : "text-red-600";
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-neutral-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${cls}`} style={{ width: `${Math.max(4, pct)}%` }} />
      </div>
      <span className={`text-[10px] font-bold tabular-nums ${txt}`}>×{weight.toFixed(2)}</span>
    </div>
  );
}

function WinRateBadge({ rate, total }: { rate: number; total: number }) {
  const cls = total < 5 ? "text-neutral-400" : rate >= 65 ? "text-green-600" : rate >= 50 ? "text-yellow-600" : "text-red-500";
  return (
    <div className="text-right">
      <p className={`text-sm font-black tabular-nums ${cls}`}>{rate.toFixed(0)}%</p>
      <p className="text-[9px] text-neutral-400">{total} trades</p>
    </div>
  );
}

function ReliabilityBadge({ r }: { r: "high" | "medium" | "low" }) {
  const map = {
    high:   "bg-green-100 text-green-700 border-green-200",
    medium: "bg-yellow-100 text-yellow-700 border-yellow-200",
    low:    "bg-neutral-100 text-neutral-500 border-neutral-200",
  };
  return (
    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${map[r]}`}>
      {r === "high" ? "✦ High" : r === "medium" ? "◈ Med" : "◇ Low"}
    </span>
  );
}

// ── HitRateBar ────────────────────────────────────────────────────────────────

function HitRateBar({ value, label, threshold = 50 }: { value: number; label: string; threshold?: number }) {
  const pct = Math.min(100, Math.max(0, value));
  const good = pct >= threshold;
  const color = pct >= 60 ? "bg-green-500" : pct >= 45 ? "bg-yellow-400" : "bg-red-400";
  const textColor = pct >= 60 ? "text-green-700" : pct >= 45 ? "text-yellow-600" : "text-red-600";
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-neutral-500 w-12 shrink-0">{label}</span>
      <div className="flex-1 relative h-2 bg-neutral-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
        {/* Threshold marker at 50% */}
        <div className="absolute top-0 bottom-0 w-px bg-neutral-400 opacity-60" style={{ left: `${threshold}%` }} />
      </div>
      <span className={`text-xs font-black tabular-nums w-10 text-right ${textColor}`}>{pct.toFixed(0)}%</span>
      <span className="text-[10px]">{good ? "✓" : "✗"}</span>
    </div>
  );
}

// ── AgentHealthCards ──────────────────────────────────────────────────────────

const LANE_ICONS: Record<string, string> = {
  pre_gainer:   "🎯",
  accumulation: "🪣",
  momentum:     "⚡",
  bigmover:     "🚀",
};

const LANE_COLORS: Record<string, string> = {
  pre_gainer:   "border-blue-200 bg-blue-50",
  accumulation: "border-purple-200 bg-purple-50",
  momentum:     "border-orange-200 bg-orange-50",
  bigmover:     "border-red-200 bg-red-50",
};

function AgentHealthCards({ health }: { health: AgentHealthData | null }) {
  if (!health) return null;
  const gateOpen = !health.gate.active;

  return (
    <div className="space-y-3">
      {/* System status banner */}
      <div className={`flex flex-wrap items-center gap-3 px-4 py-3 rounded-xl border ${gateOpen ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200"}`}>
        <span className={`text-sm font-bold ${gateOpen ? "text-green-700" : "text-red-700"}`}>
          {gateOpen ? "🟢 Gate: Terbuka" : `🔴 Gate: ${health.gate.gate_type.replace("_", " ").toUpperCase()}`}
        </span>
        <span className="text-xs text-neutral-500">·</span>
        <span className="text-xs text-neutral-600 font-mono">
          Scan #{health.scan.cycle_count ?? "—"}
        </span>
        <span className="text-xs text-neutral-500">·</span>
        <span className="text-xs text-neutral-600">
          {health.scan.next_scan_in_min != null
            ? `Berikutnya ${health.scan.next_scan_in_min.toFixed(1)} mnt`
            : health.scan.last_scan_ts
              ? `Terakhir ${new Date(health.scan.last_scan_ts * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}`
              : "Belum scan"}
        </span>
        <span className="text-xs text-neutral-500">·</span>
        <span className="text-xs font-bold text-indigo-600">
          🧠 {health.learning.cached_keys} sinyal dipelajari
        </span>
        {health.learning.blacklisted_count > 0 && (
          <>
            <span className="text-xs text-neutral-500">·</span>
            <span className="text-xs font-semibold text-orange-600">
              ⛔ {health.learning.blacklisted_count} koin blacklist
            </span>
          </>
        )}
        {health.gate.drawdown_pct != null && (
          <>
            <span className="text-xs text-neutral-500">·</span>
            <span className="text-xs text-neutral-500 tabular-nums">
              DD {health.gate.drawdown_pct.toFixed(1)}% / {health.gate.dd_threshold}%
            </span>
          </>
        )}
      </div>

      {/* Gate warning when active */}
      {health.gate.active && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-xs text-red-700">
          <span className="font-bold">⛔ Risk Gate Aktif: </span>{health.gate.reason}
        </div>
      )}

      {/* Per-lane cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {health.lanes.map(lane => {
          const wr = lane.wr * 100;
          const wrColor = lane.trades < 10 ? "text-neutral-400" : wr >= 55 ? "text-green-600" : wr >= 40 ? "text-yellow-600" : "text-red-500";
          return (
            <div key={lane.lane} className={`rounded-xl border p-3 ${lane.paused ? "border-orange-300 bg-orange-50" : LANE_COLORS[lane.lane] ?? "bg-neutral-50 border-neutral-200"}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-base">{LANE_ICONS[lane.lane] ?? "📊"}</span>
                {lane.paused ? (
                  <span className="text-[9px] bg-orange-100 text-orange-700 border border-orange-200 px-1.5 py-0.5 rounded-full font-bold">PAUSED</span>
                ) : (
                  <span className="text-[9px] bg-green-100 text-green-700 border border-green-200 px-1.5 py-0.5 rounded-full font-bold">ACTIVE</span>
                )}
              </div>
              <p className="text-xs font-bold text-neutral-800 mb-1">{lane.label}</p>
              <div className="flex items-baseline gap-1">
                <span className={`text-xl font-black tabular-nums ${wrColor}`}>
                  {lane.trades >= 5 ? `${wr.toFixed(0)}%` : "—"}
                </span>
                <span className="text-[9px] text-neutral-400">WR</span>
              </div>
              <p className="text-[9px] text-neutral-400 mt-0.5">{lane.trades} trades rolling</p>
              {lane.paused && lane.pause_until && (
                <p className="text-[9px] text-orange-600 mt-1">
                  Resume {new Date(lane.pause_until * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* Blacklisted coins (when present) */}
      {health.learning.blacklisted_coins.length > 0 && (
        <div className="bg-orange-50 border border-orange-200 rounded-xl px-4 py-3">
          <p className="text-[10px] font-bold text-orange-700 uppercase tracking-wider mb-2">
            ⛔ Koin Blacklist (3× SL berturut — 24h cooldown)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {health.learning.blacklisted_coins.map(c => (
              <span key={c} className="bg-orange-100 text-orange-800 border border-orange-200 text-[10px] font-bold px-2 py-0.5 rounded-full">
                {c.replace("USDT", "")}
              </span>
            ))}
            {health.learning.bl_directional.map(b => (
              <span key={`${b.symbol}-${b.direction}`} className="bg-orange-50 text-orange-600 border border-orange-200 text-[10px] px-2 py-0.5 rounded-full">
                {b.symbol.replace("USDT", "")} {b.direction}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── UpdaterStatus ─────────────────────────────────────────────────────────────

function LearningLoopStatus({ state, onForce }: { state: UpdaterState | null; onForce: () => void }) {
  const fmt = (ts?: number) => ts ? new Date(ts * 1000).toLocaleTimeString("id-ID") : "—";
  const items = [
    { label: "SPOT",        last: state?.spot?.last_run,    error: state?.spot?.last_error,    extra: state?.spot?.last_count != null ? `${state.spot.last_count} keys` : "" },
    { label: "Futures",     last: state?.futures?.last_run, error: state?.futures?.last_error, extra: (state?.futures?.cached_agents ?? []).join(", ") || "" },
    { label: "Cross-Agent", last: state?.cross?.last_run,   error: state?.cross?.last_error,   extra: state?.cross?.cached_keys != null ? `${state.cross.cached_keys} keys` : "" },
  ];
  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">⚙️ Learning Loop Status</p>
        <button onClick={onForce}
          className="text-xs bg-teal-600 text-white px-3 py-1 rounded-lg font-semibold hover:bg-teal-500 transition-colors">
          ↺ Force Update
        </button>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {items.map(x => (
          <div key={x.label} className={`rounded-xl p-3 ${x.error ? "bg-red-50 border border-red-100" : "bg-neutral-50"}`}>
            <p className="text-[10px] font-bold text-neutral-500 uppercase mb-1">{x.label}</p>
            <p className="text-xs font-mono font-semibold text-neutral-800">{fmt(x.last)}</p>
            {x.extra && <p className="text-[9px] text-neutral-400 mt-0.5">{x.extra}</p>}
            {x.error && <p className="text-[9px] text-red-500 mt-0.5 truncate">{x.error}</p>}
          </div>
        ))}
      </div>
      <p className="text-[10px] text-neutral-400 mt-3">
        Bobot naik/turun otomatis setiap siklus scan. Cross-agent blending aktif jika sinyal muncul di ≥2 agen.
      </p>
    </div>
  );
}

function AdaptiveEnginePanel({ data, compact = false }: { data: AdaptiveEngineData | null; compact?: boolean }) {
  if (!data) {
    return <div className="bg-white border border-neutral-200 rounded-2xl p-5 text-sm text-neutral-400">Adaptive Engine belum tersedia.</div>;
  }
  const statusMap = {
    degraded:  { label: "Degraded",  cls: "bg-red-100 text-red-700 border-red-200", dot: "bg-red-500" },
    collecting: { label: "Collecting", cls: "bg-blue-100 text-blue-700 border-blue-200", dot: "bg-blue-500" },
    shadow:    { label: "Shadow",    cls: "bg-purple-100 text-purple-700 border-purple-200", dot: "bg-purple-500" },
    canary:    { label: "Canary",    cls: "bg-amber-100 text-amber-700 border-amber-200", dot: "bg-amber-500" },
    champion:  { label: "Champion",  cls: "bg-green-100 text-green-700 border-green-200", dot: "bg-green-500" },
  } as const;
  const status = statusMap[data.engine_status] ?? statusMap.degraded;
  const qualityIssues = Object.values(data.decision_ledger.quality).reduce((sum, value) => sum + value, 0);
  const latestModel = data.models[0];
  const gateLabels: Record<string, string> = {
    training_data: "60 mature samples", test_samples: "20 OOS samples",
    promotion_eligible: "Promotion eligible", outcome_completeness: "Outcome ≥99%",
    data_quality: "Data quality", champion_exists: "Champion active", rollback_ready: "Rollback ready",
  };
  return (
    <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
      <div className="p-4 border-b border-neutral-100 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">Adaptive Learning Engine · SPOT</p>
          <p className="text-[11px] text-neutral-400 mt-0.5">Decision ledger → outcomes → calibrated challenger → shadow → canary → champion</p>
        </div>
        <span className={`inline-flex items-center gap-2 text-xs font-bold border rounded-full px-3 py-1 ${status.cls}`}>
          <span className={`w-2 h-2 rounded-full ${status.dot}`} />{status.label}
        </span>
      </div>

      {/* Baris awam — apa arti status ini (U2) */}
      <div className="px-4 py-2.5 bg-neutral-50 border-b border-neutral-100 text-[11px] leading-relaxed text-neutral-600">
        💡 <strong>Artinya:</strong> {ENGINE_STATUS_PLAIN[data.engine_status] ?? "Status tidak dikenal."}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-neutral-100">
        {[
          { label: "Decision Events", value: data.decision_ledger.total.toLocaleString("id-ID"), sub: `${data.decision_ledger.actions.rejected ?? 0} hard rejected` },
          { label: "Mature Features", value: `${data.training.mature_feature_samples}/${data.training.required_samples}`, sub: `${data.training.progress_pct.toFixed(1)}% menuju training` },
          { label: "Outcome 24h", value: `${data.decision_ledger.outcome_completeness_pct.toFixed(1)}%`, sub: `${data.decision_ledger.labelled_24h}/${data.decision_ledger.due_24h} due events` },
          { label: "Data Quality", value: qualityIssues === 0 ? "Clean" : `${qualityIssues} issue`, sub: qualityIssues === 0 ? "No leakage / duplicate" : "Perlu investigasi" },
        ].map(card => (
          <div key={card.label} className="bg-white p-4">
            <p className="text-[10px] uppercase tracking-wider font-bold text-neutral-400">{card.label}</p>
            <p className="text-2xl font-black text-neutral-800 mt-1 tabular-nums">{card.value}</p>
            <p className="text-[10px] text-neutral-400 mt-0.5">{card.sub}</p>
          </div>
        ))}
      </div>

      <div className="p-4">
        <div className="flex items-center justify-between text-[10px] mb-1.5">
          <span className="font-bold text-neutral-500">Training evidence</span>
          <span className="font-mono text-neutral-400">{data.training.progress_pct.toFixed(1)}%</span>
        </div>
        <div className="h-2 rounded-full bg-neutral-100 overflow-hidden">
          <div className="h-full rounded-full bg-gradient-to-r from-teal-500 to-blue-500" style={{ width: `${Math.max(1, data.training.progress_pct)}%` }} />
        </div>
      </div>

      {!compact && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 p-4 pt-0">
          <div className="rounded-xl border border-neutral-200 p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Promotion Gates</p>
            <div className="space-y-1.5">
              {Object.entries(data.gates).map(([key, passed]) => (
                <div key={key} className="flex items-center justify-between text-[11px]">
                  <span className="text-neutral-600">{gateLabels[key] ?? key}</span>
                  <span className={`font-bold ${passed ? "text-green-600" : "text-neutral-400"}`}>{passed ? "PASS" : "WAIT"}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-xl border border-neutral-200 p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Model Registry</p>
            {latestModel ? (
              <div className="space-y-1.5 text-[11px]">
                <p className="font-mono text-neutral-700 truncate" title={latestModel.version}>{latestModel.version}</p>
                <p className="text-neutral-500">Status <strong className="capitalize text-neutral-800">{latestModel.status}</strong></p>
                <p className="text-neutral-500">Training n <strong className="text-neutral-800">{latestModel.training_n}</strong></p>
                <p className={latestModel.promotion_eligible ? "text-green-600 font-bold" : "text-amber-600 font-bold"}>
                  {latestModel.promotion_eligible ? "Eligible for canary" : "Promotion blocked"}
                </p>
              </div>
            ) : <p className="text-[11px] text-neutral-400">Belum ada model—menunggu evidence matang.</p>}
          </div>
          <div className="rounded-xl border border-neutral-200 p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Walk-forward & On-chain</p>
            <div className="space-y-1.5 text-[11px] text-neutral-500">
              <p>Walk-forward <strong className="text-neutral-800">{data.walkforward.status}</strong> · n={data.walkforward.n ?? 0}</p>
              <p>Best threshold <strong className="text-neutral-800">{data.walkforward.best_threshold ?? "—"}</strong></p>
              <p>OOS expectancy <strong className="text-neutral-800">{data.walkforward.test?.expectancy_pct?.toFixed(2) ?? "—"}%</strong></p>
              <p>On-chain <strong className="text-neutral-800">{data.onchain.mode ?? "unavailable"}</strong> · {data.onchain.cache_entries ?? 0} cached</p>
              <p className="font-mono text-[9px] text-neutral-400">{data.onchain.mapping_version ?? "no mapping"}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── FuturesAdaptiveEnginePanel (F6) ────────────────────────────────────────────

function FuturesAdaptiveEnginePanel({ data, compact = false }: { data: FuturesAdaptiveEngineData | null; compact?: boolean }) {
  if (!data) {
    return <div className="bg-white border border-neutral-200 rounded-2xl p-5 text-sm text-neutral-400">Futures Adaptive Engine belum tersedia.</div>;
  }
  const statusMap = {
    degraded:      { label: "Degraded",       cls: "bg-red-100 text-red-700 border-red-200",       dot: "bg-red-500" },
    collecting:    { label: "Collecting",     cls: "bg-blue-100 text-blue-700 border-blue-200",     dot: "bg-blue-500" },
    ready_to_train:{ label: "Ready to Train", cls: "bg-teal-100 text-teal-700 border-teal-200",     dot: "bg-teal-500" },
    shadow:        { label: "Shadow",         cls: "bg-purple-100 text-purple-700 border-purple-200", dot: "bg-purple-500" },
    canary:        { label: "Canary",         cls: "bg-amber-100 text-amber-700 border-amber-200",   dot: "bg-amber-500" },
    champion:      { label: "Champion",       cls: "bg-green-100 text-green-700 border-green-200",   dot: "bg-green-500" },
  } as const;
  const status = statusMap[data.engine_status] ?? statusMap.degraded;
  const latestModel = data.models[0];
  const learnMap: Record<string, string> = {
    warming: "text-amber-600", active: "text-green-600", degraded: "text-red-600",
  };
  const qualityIssues = Object.values(data.decision_ledger.quality).reduce((s, v) => s + v, 0);
  const phaseLabels: Record<string, string> = {
    F0_policy: "F0 Policy", F1_ledger: "F1 Ledger", F2_integration: "F2 Integrasi",
    F3_model: "F3 Model", F4_walkforward: "F4 Walk-fwd", F5_canary: "F5 Canary",
  };
  const gateLabels: Record<string, string> = {
    training_data: "60 mature samples", outcome_completeness: "Outcome ≥99%",
    data_quality: "Data quality", model_trained: "Model trained", canary_passed: "Canary passed",
    promotion_eligible: "Model lolos uji offline", walkforward_passed: "Lolos walk-forward + stress",
    canary_active: "Uji coba canary berjalan", champion_exists: "Model champion aktif",
  };
  // Reason codes teratas (selain opened/recommendation) — kenapa kandidat tidak dibuka
  const topReasons = Object.entries(data.decision_ledger.reasons)
    .filter(([r]) => r !== "opened" && r !== "not_evaluated")
    .sort((a, b) => b[1] - a[1]).slice(0, 6);
  return (
    <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
      <div className="p-4 border-b border-neutral-100 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">Adaptive Learning Engine · FUTURES</p>
          <p className="text-[11px] text-neutral-400 mt-0.5">Decision ledger → outcomes (NET true-cost) → challenger → canary · veto-only</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-bold ${learnMap[data.learning_status] ?? "text-neutral-500"}`}>
            learning: {data.learning_status}
          </span>
          <span className={`inline-flex items-center gap-2 text-xs font-bold border rounded-full px-3 py-1 ${status.cls}`}>
            <span className={`w-2 h-2 rounded-full ${status.dot}`} />{status.label}
          </span>
        </div>
      </div>

      {/* Baris awam — apa arti status ini (U2) */}
      <div className="px-4 py-2.5 bg-neutral-50 border-b border-neutral-100 text-[11px] leading-relaxed text-neutral-600">
        💡 <strong>Artinya:</strong> {ENGINE_STATUS_PLAIN[data.engine_status] ?? "Status tidak dikenal."}{" "}
        Saat ini {LEARNING_STATUS_PLAIN[data.learning_status] ?? data.learning_status}.
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-px bg-neutral-100">
        {[
          { label: "Decision Events", value: data.decision_ledger.total.toLocaleString("id-ID"), sub: `${data.decision_ledger.opened} opened · ${data.decision_ledger.actions.rejected ?? 0} rejected` },
          { label: "Mature Features", value: `${data.training.mature_feature_samples}/${data.training.required_samples}`, sub: `${data.training.progress_pct.toFixed(1)}% menuju training F3` },
          { label: "Outcome 24h", value: `${data.decision_ledger.outcome_completeness_pct.toFixed(1)}%`, sub: `${data.decision_ledger.labelled_24h}/${data.decision_ledger.due_24h} due · ${data.decision_ledger.realized_linked} trade linked` },
          { label: "Data Quality", value: qualityIssues === 0 ? "Clean" : `${qualityIssues} issue`, sub: qualityIssues === 0 ? "No leakage / duplicate" : "Perlu investigasi" },
        ].map(card => (
          <div key={card.label} className="bg-white p-4">
            <p className="text-[10px] uppercase tracking-wider font-bold text-neutral-400">{card.label}</p>
            <p className="text-2xl font-black text-neutral-800 mt-1 tabular-nums">{card.value}</p>
            <p className="text-[10px] text-neutral-400 mt-0.5">{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Progres fase F0-F5 */}
      <div className="p-4 border-b border-neutral-100">
        <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Progres Engine</p>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(data.phases).map(([key, done]) => (
            <span key={key} className={`text-[10px] font-bold rounded-md px-2 py-1 border ${done ? "bg-green-50 text-green-700 border-green-200" : "bg-neutral-50 text-neutral-400 border-neutral-200"}`}>
              {done ? "✓ " : "○ "}{phaseLabels[key] ?? key}
            </span>
          ))}
        </div>
      </div>

      <div className="p-4">
        <div className="flex items-center justify-between text-[10px] mb-1.5">
          <span className="font-bold text-neutral-500">Training evidence (ledger matang → F3 model)</span>
          <span className="font-mono text-neutral-400">{data.training.progress_pct.toFixed(1)}%</span>
        </div>
        <div className="h-2 rounded-full bg-neutral-100 overflow-hidden">
          <div className="h-full rounded-full bg-gradient-to-r from-teal-500 to-blue-500" style={{ width: `${Math.max(1, data.training.progress_pct)}%` }} />
        </div>
      </div>

      {!compact && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 p-4 pt-0">
          <div className="rounded-xl border border-neutral-200 p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Acceptance Gates</p>
            <div className="space-y-1.5">
              {Object.entries(data.gates).map(([key, passed]) => (
                <div key={key} className="flex items-center justify-between text-[11px]">
                  <span className="text-neutral-600">{gateLabels[key] ?? key}</span>
                  <span className={`font-bold ${passed ? "text-green-600" : "text-neutral-400"}`}>{passed ? "PASS" : "WAIT"}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-xl border border-neutral-200 p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Kenapa tidak dibuka (top reasons)</p>
            {topReasons.length ? (
              <div className="space-y-1 text-[11px]">
                {topReasons.map(([reason, n]) => (
                  <div key={reason} className="flex items-center justify-between gap-2">
                    <span className="text-neutral-600 min-w-0" title={reason}>
                      {REASON_LABELS[reason] ?? reason}
                      <span className="block font-mono text-[9px] text-neutral-400 truncate">{reason}</span>
                    </span>
                    <span className="font-bold text-neutral-800 tabular-nums shrink-0">{n.toLocaleString("id-ID")}</span>
                  </div>
                ))}
              </div>
            ) : <p className="text-[11px] text-neutral-400">Belum ada keputusan tercatat.</p>}
          </div>
        </div>
      )}

      {!compact && data.walkforward && data.walkforward.status === "ok" && (
        <div className="p-4 pt-0">
          <div className="rounded-xl border border-neutral-200 p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Walk-forward + cost-stress 1.5× (F4 — diagnostik)</p>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 text-[11px]">
              <div><span className="text-neutral-500">Best threshold</span><p className="font-bold text-neutral-800 tabular-nums">{data.walkforward.best_threshold ?? "—"}</p></div>
              <div><span className="text-neutral-500">OOS expectancy</span><p className="font-bold text-neutral-800 tabular-nums">{data.walkforward.test?.expectancy_pct?.toFixed(3) ?? "—"}%</p></div>
              <div><span className="text-neutral-500">OOS PF</span><p className="font-bold text-neutral-800 tabular-nums">{data.walkforward.test?.profit_factor ?? "—"}</p></div>
              <div><span className="text-neutral-500">Stress 1.5× exp</span><p className={`font-bold tabular-nums ${(data.walkforward.test_stressed_1_5x?.expectancy_pct ?? -1) > 0 ? "text-green-700" : "text-red-600"}`}>{data.walkforward.test_stressed_1_5x?.expectancy_pct?.toFixed(3) ?? "—"}%</p></div>
            </div>
            <p className={`mt-2 text-[11px] font-bold ${data.walkforward.promotion_eligible ? "text-green-600" : "text-amber-600"}`}>
              {data.walkforward.promotion_eligible ? "Walk-forward lolos (tahan cost-stress 1.5×)" : "Walk-forward belum lolos gate (incl. cost-stress)"}
            </p>
          </div>
        </div>
      )}

      {!compact && latestModel && (
        <div className="p-4 pt-0">
          <div className="rounded-xl border border-neutral-200 p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">Model Registry (challenger — shadow, tak memengaruhi keputusan)</p>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 text-[11px]">
              <div><span className="text-neutral-500">Versi</span><p className="font-mono text-neutral-800 truncate" title={latestModel.version}>{latestModel.version}</p></div>
              <div><span className="text-neutral-500">Status</span><p className="capitalize font-bold text-neutral-800">{latestModel.status} · {latestModel.label_horizon}</p></div>
              <div><span className="text-neutral-500">Training n</span><p className="font-bold text-neutral-800 tabular-nums">{latestModel.training_n}</p></div>
              <div><span className="text-neutral-500">OOS Brier</span><p className="font-bold text-neutral-800 tabular-nums">{latestModel.test?.brier?.toFixed(4) ?? "—"}</p></div>
            </div>
            <p className={`mt-2 text-[11px] font-bold ${latestModel.promotion_eligible ? "text-green-600" : "text-amber-600"}`}>
              {latestModel.promotion_eligible ? "Eligible for canary (F5)" : "Promotion blocked — belum lolos gate offline"}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── SortTh ───────────────────────────────────────────────────────────────────

function SortTh({ col, label, sortBy, setSortBy, sortDir, setSortDir }: {
  col: SortBy; label: string;
  sortBy: SortBy; setSortBy: (s: SortBy) => void;
  sortDir: "desc" | "asc"; setSortDir: (d: "desc" | "asc") => void;
}) {
  return (
    <button className="flex items-center gap-0.5 hover:text-neutral-700 transition-colors"
      onClick={() => {
        if (sortBy === col) setSortDir(sortDir === "desc" ? "asc" : "desc");
        else { setSortBy(col); setSortDir("desc"); }
      }}>
      {label}
      <span className="text-[10px]">{sortBy === col ? (sortDir === "desc" ? "↓" : "↑") : "↕"}</span>
    </button>
  );
}

// ── SignalTable ───────────────────────────────────────────────────────────────

function SignalTable({ signals, agentKey, sortBy, setSortBy, sortDir, setSortDir, catalog }: {
  signals: SignalRow[];
  agentKey: string;
  sortBy: SortBy;
  setSortBy: (s: SortBy) => void;
  sortDir: "desc" | "asc";
  setSortDir: (d: "desc" | "asc") => void;
  catalog?: CatalogResponse | null;
}) {
  if (signals.length === 0) return (
    <div className="text-center py-10 text-neutral-400 text-sm">Belum ada data sinyal dengan filter ini</div>
  );

  return (
    <div className="overflow-hidden rounded-xl border border-neutral-200">
      <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 px-4 py-2 bg-neutral-50 border-b border-neutral-200 text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
        <span>Signal</span>
        <SortTh col="win_rate"    label="Win Rate" sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir} />
        <SortTh col="avg_pnl_pct" label="Avg PnL%" sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir} />
        <SortTh col="total_count" label="Trades"   sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir} />
        <SortTh col="weight"      label="Weight"   sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir} />
      </div>
      <div className="divide-y divide-neutral-100">
        {signals.map(s => {
          const agentData = agentKey === "all"
            ? Object.values(s.agents)[0]
            : s.agents[agentKey];
          if (!agentData) return null;
          // Prefer catalog human label over raw normalized key
          const catEntry = catalog?.catalog?.[s.signal_key];
          const displayLabel = catEntry?.label ?? s.signal_key.replace(/_/g, " ");
          const catColor = catEntry ? "text-neutral-800" : "text-neutral-500";
          return (
            <div key={s.signal_key} className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 px-4 py-2.5 items-center hover:bg-neutral-50">
              <div>
                <p className={`text-xs font-semibold font-mono truncate max-w-xs ${catColor}`}>
                  {displayLabel}
                </p>
                {catEntry && (
                  <p className="text-[9px] text-neutral-400 font-normal mt-0.5">{s.signal_key}</p>
                )}
                {s.cross_weight && (
                  <span className="text-[9px] text-purple-600 font-semibold">
                    cross ×{s.cross_weight.toFixed(2)}
                  </span>
                )}
              </div>
              <WinRateBadge rate={agentData.win_rate} total={agentData.total} />
              <div className="text-right w-16">
                <span className={`text-xs font-bold tabular-nums ${agentData.avg_pnl_pct > 0 ? "text-green-600" : agentData.avg_pnl_pct < 0 ? "text-red-500" : "text-neutral-400"}`}>
                  {agentData.avg_pnl_pct > 0 ? "+" : ""}{agentData.avg_pnl_pct.toFixed(1)}%
                </span>
              </div>
              <div className="text-right w-12">
                <span className="text-xs text-neutral-600 tabular-nums">{agentData.total}</span>
              </div>
              <WeightBar weight={agentData.weight} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── CrossAgentTable ───────────────────────────────────────────────────────────

function CrossAgentTable({ signals }: { signals: CrossSignalRow[] }) {
  if (signals.length === 0) return (
    <div className="text-center py-10 text-neutral-400 text-sm">
      Belum ada sinyal dengan data cross-agent yang cukup (min 10 trades)
    </div>
  );

  return (
    <div className="space-y-2">
      {signals.map(s => (
        <div key={s.signal_key} className="bg-white border border-neutral-200 rounded-xl p-3">
          <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-bold font-mono text-neutral-800">
                {s.signal_key.replace(/_/g, " ")}
              </span>
              <ReliabilityBadge r={s.reliability} />
              <span className="text-[9px] text-neutral-400">{s.agent_count} agen · {s.cross_total} trades</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-right">
                <p className={`text-sm font-black ${s.cross_win_rate >= 65 ? "text-green-600" : s.cross_win_rate >= 50 ? "text-yellow-600" : "text-red-500"}`}>
                  {s.cross_win_rate.toFixed(0)}%
                </p>
                <p className="text-[9px] text-neutral-400">win rate</p>
              </div>
              <div className="text-right">
                <p className={`text-sm font-black ${s.avg_pnl_pct > 0 ? "text-green-600" : "text-red-500"}`}>
                  {s.avg_pnl_pct > 0 ? "+" : ""}{s.avg_pnl_pct.toFixed(1)}%
                </p>
                <p className="text-[9px] text-neutral-400">avg PnL</p>
              </div>
              <WeightBar weight={s.cross_weight} />
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(s.agents).map(([agent, data]) => (
              <div key={agent} className="bg-neutral-50 rounded-lg px-2 py-1 text-[10px]">
                <span className="text-neutral-500">{data.label}: </span>
                <span className={`font-bold ${data.win_rate >= 60 ? "text-green-600" : data.win_rate >= 50 ? "text-yellow-600" : "text-red-500"}`}>
                  {data.win_rate.toFixed(0)}%
                </span>
                <span className="text-neutral-400"> ({data.total})</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── RegimeHeatmap ─────────────────────────────────────────────────────────────

const REGIME_COLORS: Record<string, string> = {
  trending_up:   "bg-green-500",
  trending_down: "bg-red-500",
  ranging:       "bg-yellow-400",
  volatile:      "bg-orange-500",
  all:           "bg-blue-500",
};

function RegimeCell({ weight }: { weight: number | null }) {
  if (weight === null) return <td className="px-2 py-2 text-center text-[9px] text-neutral-300">—</td>;
  const dev = weight - 1.0;
  const bg  = dev > 0.15 ? "bg-green-100 text-green-700" : dev < -0.15 ? "bg-red-100 text-red-700" : dev > 0.05 ? "bg-teal-50 text-teal-600" : dev < -0.05 ? "bg-orange-50 text-orange-600" : "bg-neutral-50 text-neutral-500";
  return (
    <td className={`px-2 py-2 text-center text-[10px] font-bold tabular-nums rounded ${bg}`}>
      ×{weight.toFixed(2)}
    </td>
  );
}

function RegimeHeatmap({ regimeData }: { regimeData: RegimeResponse | null }) {
  if (!regimeData) return <div className="text-center py-10 text-neutral-400 text-sm">Memuat data regime...</div>;
  if (regimeData.signals.length === 0) return (
    <div className="text-center py-10 text-neutral-400 text-sm">
      Belum ada data regime-specific. Weight akan terbentuk setelah ≥3 trade per regime ter-close.
    </div>
  );
  const REGIMES = ["all", "trending_up", "trending_down", "ranging", "volatile"];
  const REGIME_LABELS: Record<string, string> = {
    all: "All", trending_up: "Trending ↑", trending_down: "Trending ↓", ranging: "Ranging", volatile: "Volatile",
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-neutral-50 border-b border-neutral-200">
            <th className="text-left px-3 py-2 font-bold text-neutral-500 uppercase text-[9px] tracking-wider min-w-[200px]">Signal</th>
            {REGIMES.map(r => (
              <th key={r} className="px-2 py-2 text-center text-[9px] font-bold text-neutral-500 uppercase tracking-wider">
                <span className={`inline-block w-2 h-2 rounded-full mr-1 ${REGIME_COLORS[r] ?? "bg-neutral-400"}`} />
                {REGIME_LABELS[r]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100">
          {regimeData.signals.map(s => (
            <tr key={s.signal_key} className="hover:bg-neutral-50">
              <td className="px-3 py-2">
                <span className="font-mono text-[11px] text-neutral-700">{s.signal_key.replace(/_/g, " ")}</span>
              </td>
              {REGIMES.map(r => <RegimeCell key={r} weight={s.regimes[r] ?? null} />)}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-neutral-400 mt-3 px-1">
        Hijau = weight &gt; 1.0 (profitable di regime ini). Merah = weight &lt; 1.0 (underperform).
        Aktif sejak PLAN_v2 P3.5.
      </p>
    </div>
  );
}

// ── FormulasTab ───────────────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  volatility:    "bg-blue-50 border-blue-200 text-blue-700",
  volume:        "bg-teal-50 border-teal-200 text-teal-700",
  funding:       "bg-purple-50 border-purple-200 text-purple-700",
  open_interest: "bg-orange-50 border-orange-200 text-orange-700",
  momentum:      "bg-yellow-50 border-yellow-200 text-yellow-700",
  structure:     "bg-neutral-50 border-neutral-200 text-neutral-600",
  composite:     "bg-green-50 border-green-200 text-green-700",
  magnitude:     "bg-red-50 border-red-200 text-red-700",
  breakout:      "bg-cyan-50 border-cyan-200 text-cyan-700",
  wyckoff:       "bg-indigo-50 border-indigo-200 text-indigo-700",
};

function FormulasTab({ catalog }: { catalog: CatalogResponse | null }) {
  const [catFilter, setCatFilter] = useState<string>("all");
  if (!catalog) return <div className="text-center py-10 text-neutral-400 text-sm">Memuat katalog...</div>;
  const entries = Object.entries(catalog.catalog);
  const filtered = catFilter === "all" ? entries : entries.filter(([, e]) => e.category === catFilter);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        <button onClick={() => setCatFilter("all")}
          className={`px-3 py-1 rounded-full text-[10px] font-bold border transition-all ${catFilter === "all" ? "bg-neutral-800 text-white border-neutral-800" : "bg-white text-neutral-500 border-neutral-200"}`}>
          All ({entries.length})
        </button>
        {catalog.categories.map(c => (
          <button key={c} onClick={() => setCatFilter(c)}
            className={`px-3 py-1 rounded-full text-[10px] font-bold border transition-all capitalize ${catFilter === c ? "bg-neutral-800 text-white border-neutral-800" : `${CATEGORY_COLORS[c] ?? "bg-white text-neutral-500 border-neutral-200"}`}`}>
            {c.replace(/_/g, " ")}
          </button>
        ))}
      </div>
      <div className="grid gap-3">
        {filtered.map(([key, entry]) => (
          <div key={key} className="bg-white border border-neutral-200 rounded-xl p-4">
            <div className="flex items-start justify-between gap-3 mb-2">
              <div>
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="font-bold text-sm text-neutral-800">{entry.label}</span>
                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border capitalize ${CATEGORY_COLORS[entry.category] ?? "bg-neutral-50 border-neutral-200 text-neutral-500"}`}>
                    {entry.category.replace(/_/g, " ")}
                  </span>
                </div>
                <code className="text-[9px] text-neutral-400 font-mono">{key}</code>
              </div>
              <span className="text-[9px] text-neutral-400 bg-neutral-50 px-2 py-1 rounded-lg font-mono whitespace-nowrap">
                {entry.score_impact_formula}
              </span>
            </div>
            <p className="text-xs text-neutral-600 mb-3">{entry.description}</p>
            <div className="flex flex-wrap gap-1.5">
              {entry.agents.map(a => (
                <div key={a.agent} className="bg-neutral-50 rounded-lg px-2 py-1 text-[10px]">
                  <span className="font-bold text-neutral-700">{a.label}</span>
                  <span className="text-neutral-400"> · max {a.max_pts} pts · </span>
                  <code className="text-teal-600 text-[9px]">{a.fn}()</code>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── PredictivePanel ───────────────────────────────────────────────────────────

function PredictivePanel({ data }: { data: PredictiveHitRow[] | null }) {
  if (!data) return (
    <div className="flex items-center justify-center py-16 text-neutral-400 gap-2">
      <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
      Memuat...
    </div>
  );
  if (data.length === 0) return (
    <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-6 text-center space-y-2">
      <p className="text-2xl">🔮</p>
      <p className="text-sm font-bold text-indigo-800">Belum ada prediction yang resolve</p>
      <p className="text-xs text-indigo-600">
        Sistem mencatat setiap kandidat yang di-scan. Setelah 4h dan 24h,
        harga dicek apakah bergerak ke arah yang diprediksi.
        Predictions resolve otomatis setiap ~24 menit.
      </p>
      <p className="text-[10px] text-indigo-400 mt-2">
        Hit threshold: 4h ≥1.5% · 24h ≥3.0%
      </p>
    </div>
  );

  // Compute overall quality
  const totalRows = data.length;
  const avgHit4h  = data.reduce((s, r) => s + r.hit_rate_4h, 0) / totalRows;
  const bestRow   = [...data].sort((a, b) => b.hit_rate_4h - a.hit_rate_4h)[0];
  const totalPred = data.reduce((s, r) => s + r.total, 0);
  const overallQuality = avgHit4h >= 55 ? "SANGAT BAIK" : avgHit4h >= 45 ? "BAIK" : avgHit4h >= 35 ? "CUKUP" : "PERLU PERBAIKAN";
  const qualityColor = avgHit4h >= 55 ? "text-green-700 bg-green-50 border-green-200" : avgHit4h >= 45 ? "text-teal-700 bg-teal-50 border-teal-200" : avgHit4h >= 35 ? "text-yellow-700 bg-yellow-50 border-yellow-200" : "text-red-700 bg-red-50 border-red-200";

  // Group by agent label
  const AGENT_SHORT: Record<string, string> = {
    "futures_agent1": "Pre-Gainer",
    "futures_agent2": "Accumulation",
    "futures_agent3": "Momentum",
    "futures_agent_bigmover": "BigMover",
  };

  return (
    <div className="space-y-4">
      {/* Quality summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className={`rounded-xl border px-4 py-3 ${qualityColor}`}>
          <p className="text-[10px] font-bold uppercase tracking-wider mb-1">Kualitas 4h</p>
          <p className="text-xl font-black tabular-nums">{avgHit4h.toFixed(0)}%</p>
          <p className="text-[10px] font-semibold mt-0.5">{overallQuality}</p>
        </div>
        <div className="bg-white border border-neutral-200 rounded-xl px-4 py-3">
          <p className="text-[10px] font-bold text-neutral-400 uppercase tracking-wider mb-1">Total Resolved</p>
          <p className="text-xl font-black text-neutral-800 tabular-nums">{totalPred}</p>
          <p className="text-[10px] text-neutral-400 mt-0.5">predictions</p>
        </div>
        <div className="bg-white border border-neutral-200 rounded-xl px-4 py-3">
          <p className="text-[10px] font-bold text-neutral-400 uppercase tracking-wider mb-1">Best Agent</p>
          <p className="text-sm font-black text-neutral-800">{AGENT_SHORT[bestRow.agent] ?? bestRow.agent.replace("futures_", "")}</p>
          <p className="text-[10px] text-green-600 font-semibold mt-0.5">{bestRow.direction} · {bestRow.hit_rate_4h.toFixed(0)}% hit 4h</p>
        </div>
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl px-4 py-3">
          <p className="text-[10px] font-bold text-indigo-600 uppercase tracking-wider mb-1">Threshold Hit</p>
          <p className="text-xs text-indigo-700 font-semibold">4h: ≥1.5% move</p>
          <p className="text-xs text-indigo-700 font-semibold">24h: ≥3.0% move</p>
        </div>
      </div>

      {/* Per-agent hit rate bars */}
      <div className="bg-white border border-neutral-200 rounded-xl p-4 space-y-4">
        <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">Hit Rate per Agen & Arah</p>
        {data.map(row => {
          const agentLabel = AGENT_SHORT[row.agent] ?? row.agent.replace("futures_", "");
          const dirColor = row.direction === "LONG" ? "text-green-600 bg-green-50 border-green-200" : "text-red-600 bg-red-50 border-red-200";
          return (
            <div key={`${row.agent}-${row.direction}`} className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-neutral-700 w-28">{agentLabel}</span>
                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${dirColor}`}>
                  {row.direction}
                </span>
                <span className="text-[10px] text-neutral-400">{row.total} predictions</span>
              </div>
              <div className="pl-4 space-y-1.5">
                <HitRateBar value={row.hit_rate_4h}  label="4h hit"  threshold={50} />
                <HitRateBar value={row.hit_rate_24h} label="24h hit" threshold={45} />
                <div className="flex gap-4 text-[10px] text-neutral-400 mt-1">
                  <span>avg 4h move: <span className={`font-semibold ${row.avg_move_4h > 0 ? "text-green-600" : "text-red-500"}`}>{row.avg_move_4h > 0 ? "+" : ""}{row.avg_move_4h.toFixed(1)}%</span></span>
                  <span>avg 24h move: <span className={`font-semibold ${row.avg_move_24h > 0 ? "text-green-600" : "text-red-500"}`}>{row.avg_move_24h > 0 ? "+" : ""}{row.avg_move_24h.toFixed(1)}%</span></span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-[10px] text-neutral-400 px-1">
        Garis vertikal di bar = threshold baseline (50% untuk 4h, 45% untuk 24h).
        Data ini akan digunakan untuk fine-tune weight agen secara proaktif (PLAN_v4 P2.3).
      </p>
    </div>
  );
}

// ── AdaptiveLearningTutorial ──────────────────────────────────────────────────

function AdaptiveLearningTutorial({
  onClose,
  health,
  predictive,
  adaptive,
}: {
  onClose: () => void;
  health:     AgentHealthData | null;
  predictive: PredictiveHitRow[] | null;
  adaptive:   AdaptiveEngineData | null;
}) {
  const [dontShow, setDontShow] = useState(false);

  const handleClose = () => {
    if (dontShow) localStorage.setItem("signals_tutorial_dismissed", "1");
    onClose();
  };

  const learnedKeys = health?.learning.cached_keys ?? 0;
  const blacklisted = health?.learning.blacklisted_count ?? 0;
  const totalPred   = predictive?.reduce((s, r) => s + r.total, 0) ?? 0;
  const avgHit4h    = predictive && predictive.length > 0
    ? predictive.reduce((s, r) => s + r.hit_rate_4h, 0) / predictive.length
    : null;

  const steps = [
    {
      icon: "🔍",
      title: "Scan Universe",
      desc: "Setiap 15 menit, 100 coin Binance Futures di-scan. 7 sinyal TA dihitung per coin (BB Squeeze, Volume, OI, Funding, dsb).",
      color: "border-blue-200 bg-blue-50",
      text: "text-blue-700",
    },
    {
      icon: "📊",
      title: "Score & Filter",
      desc: "Tiap sinyal punya weight (×0.7–×1.5). Score = Σ(poin × weight). Hanya coin di atas threshold (52 pts) yang masuk paper trade.",
      color: "border-teal-200 bg-teal-50",
      text: "text-teal-700",
    },
    {
      icon: "📝",
      title: "Paper Trade",
      desc: "Kandidat dicatat dengan harga entry, SL, TP, dan leverage. Monitor mengecek SL/TP setiap menit — simulasi live trading.",
      color: "border-purple-200 bg-purple-50",
      text: "text-purple-700",
    },
    {
      icon: "🧠",
      title: "Weight Update",
      desc: "Setelah trade close, weight naik jika TP hit, turun jika SL hit. Sinyal yang sering benar mendapat skor lebih besar di scan berikutnya.",
      color: "border-orange-200 bg-orange-50",
      text: "text-orange-700",
    },
    {
      icon: "🔮",
      title: "Predictive Log",
      desc: "Setiap kandidat (TP/SL atau tidak) dicatat. Setelah 4h & 24h, harga dicek. Mengukur akurasi TA murni — bukan hanya trade yang masuk.",
      color: "border-indigo-200 bg-indigo-50",
      text: "text-indigo-700",
    },
  ];

  const currentSteps = [
    { icon: "🧾", title: "Decision Ledger", desc: "Semua kandidat, hard rejection, snapshot fitur, config, dan model version dicatat secara point-in-time.", color: "border-blue-200 bg-blue-50", text: "text-blue-700" },
    { icon: "⏱️", title: "Outcome Labels", desc: "Worker mengisi PnL 1h/4h/24h/3d/7d, MAE, dan MFE hanya dari candle yang sudah close—tanpa future leakage.", color: "border-teal-200 bg-teal-50", text: "text-teal-700" },
    { icon: "⚖️", title: "Safe Decision", desc: "Weight canonical + cross-agent menghasilkan probabilitas Laplace dan Wilson lower bound untuk EV serta capped Kelly sizing.", color: "border-orange-200 bg-orange-50", text: "text-orange-700" },
    { icon: "🧪", title: "Challenger", desc: "Model logistic terkalibrasi dilatih chronological, diuji walk-forward, dan dianalisis dengan ablation sebelum masuk shadow.", color: "border-purple-200 bg-purple-50", text: "text-purple-700" },
    { icon: "🛡️", title: "Deploy & Rollback", desc: "Lifecycle shadow → canary → champion dijaga promotion gates, drift monitor, dan rollback ke last-known-good.", color: "border-green-200 bg-green-50", text: "text-green-700" },
  ];

  const tutorialSteps = adaptive ? currentSteps : steps;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white rounded-t-2xl p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[10px] text-neutral-400 uppercase tracking-wider font-semibold mb-1">Tutorial</p>
              <h2 className="text-xl font-black">Bagaimana Adaptive Learning Bekerja?</h2>
              <p className="text-sm text-neutral-400 mt-1">
                Sistem ini seperti LLM yang terus belajar dari hasil trading —
                sinyal yang profitable dapat bobot lebih, sinyal yang sering loss dikurangi.
              </p>
            </div>
            <button onClick={handleClose} className="text-neutral-400 hover:text-white transition-colors shrink-0 text-xl leading-none mt-1">×</button>
          </div>
        </div>

        <div className="p-5 space-y-5">
          {/* Loop diagram */}
          <div className="flex flex-wrap items-center justify-center gap-1.5 py-2">
            {tutorialSteps.map((step, i) => (
              <div key={step.title} className="flex items-center gap-1.5">
                <div className={`flex flex-col items-center rounded-xl border px-3 py-2.5 ${step.color} min-w-[90px]`}>
                  <span className="text-xl mb-1">{step.icon}</span>
                  <span className={`text-[10px] font-black uppercase tracking-wide ${step.text}`}>{step.title}</span>
                </div>
                {i < tutorialSteps.length - 1 && <span className="text-neutral-300 font-bold">→</span>}
              </div>
            ))}
          </div>

          {/* Step descriptions */}
          <div className="grid grid-cols-1 gap-2">
            {tutorialSteps.map(step => (
              <div key={step.title} className={`flex gap-3 rounded-xl border p-3 ${step.color}`}>
                <span className="text-base shrink-0 mt-0.5">{step.icon}</span>
                <div>
                  <p className={`text-xs font-bold mb-0.5 ${step.text}`}>{step.title}</p>
                  <p className="text-[11px] text-neutral-600 leading-relaxed">{step.desc}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Current stats */}
          {(learnedKeys > 0 || totalPred > 0) && (
            <div className="bg-neutral-50 border border-neutral-200 rounded-xl p-4">
              <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-3">Status Sistem Saat Ini</p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="text-center">
                  <p className="text-2xl font-black text-indigo-600 tabular-nums">{learnedKeys}</p>
                  <p className="text-[9px] text-neutral-400 uppercase font-semibold mt-0.5">Sinyal Dipelajari</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-black text-orange-500 tabular-nums">{blacklisted}</p>
                  <p className="text-[9px] text-neutral-400 uppercase font-semibold mt-0.5">Koin Blacklist</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-black text-blue-600 tabular-nums">{totalPred}</p>
                  <p className="text-[9px] text-neutral-400 uppercase font-semibold mt-0.5">Predictions Logged</p>
                </div>
                <div className="text-center">
                  <p className={`text-2xl font-black tabular-nums ${avgHit4h == null ? "text-neutral-400" : avgHit4h >= 50 ? "text-green-600" : "text-yellow-600"}`}>
                    {avgHit4h != null ? `${avgHit4h.toFixed(0)}%` : "—"}
                  </p>
                  <p className="text-[9px] text-neutral-400 uppercase font-semibold mt-0.5">Avg 4h Hit Rate</p>
                </div>
              </div>
            </div>
          )}

          {/* Panduan 4 seksi (selaras navigasi baru) */}
          <div className="bg-neutral-50 border border-neutral-200 rounded-xl p-4">
            <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-3">Panduan 4 Seksi</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {[
                { tab: "📊 Overview", desc: "Ringkasan cepat: kesehatan agen, mesin, sinyal teratas" },
                { tab: "🧠 Engine",   desc: "Mesin belajar adaptif SPOT & Futures — ledger, model, gate" },
                { tab: "🎯 Signals",  desc: "Bobot sinyal per market → SPOT · Futures · Cross-Agent" },
                { tab: "🔬 Analysis", desc: "Diagnostik → Regime · Formulas · Rejections · Predictive" },
              ].map(item => (
                <div key={item.tab} className="flex gap-2">
                  <span className="text-[10px] font-bold text-neutral-700 shrink-0 w-20">{item.tab}</span>
                  <span className="text-[10px] text-neutral-500">{item.desc}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between pt-1">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                className="rounded"
                checked={dontShow}
                onChange={e => setDontShow(e.target.checked)}
              />
              <span className="text-[11px] text-neutral-500">Jangan tampilkan lagi</span>
            </label>
            <button
              onClick={handleClose}
              className="bg-neutral-900 text-white text-xs font-bold px-5 py-2 rounded-xl hover:bg-neutral-700 transition-colors">
              Mengerti
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SignalsPage() {
  const [subTab,      setSubTab]      = useState<SubTab>("overview");
  const [agentFilter, setAgentFilter] = useState("futures_agent1");
  const [sortBy,      setSortBy]      = useState<SortBy>("win_rate");
  const [sortDir,     setSortDir]     = useState<"desc" | "asc">("desc");
  const [minTrades,   setMinTrades]   = useState(3);

  const [perfData,       setPerfData]       = useState<PerformanceResponse | null>(null);
  const [crossData,      setCrossData]      = useState<CrossResponse | null>(null);
  const [regimeData,     setRegimeData]     = useState<RegimeResponse | null>(null);
  const [catalogData,    setCatalogData]    = useState<CatalogResponse | null>(null);
  const [updaterState,   setUpdaterState]   = useState<UpdaterState | null>(null);
  const [rejectionsData, setRejectionsData] = useState<RejectionRow[] | null>(null);
  const [predictiveData, setPredictiveData] = useState<PredictiveHitRow[] | null>(null);
  const [agentHealth,    setAgentHealth]    = useState<AgentHealthData | null>(null);
  const [adaptiveEngine, setAdaptiveEngine] = useState<AdaptiveEngineData | null>(null);
  const [futuresEngine,  setFuturesEngine]  = useState<FuturesAdaptiveEngineData | null>(null);
  const [weightPerf,     setWeightPerf]     = useState<PerformanceResponse | null>(null);
  const [reviewData,     setReviewData]     = useState<ReviewData | null>(null);
  const [loading,        setLoading]        = useState(true);
  const [forceMsg,       setForceMsg]       = useState<string | null>(null);
  const [showTutorial,   setShowTutorial]   = useState(false);

  // Auto-show tutorial on first visit
  useEffect(() => {
    if (typeof window !== "undefined" && !localStorage.getItem("signals_tutorial_dismissed")) {
      setShowTutorial(true);
    }
  }, []);

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [perfRes, crossRes, stateRes, catalogRes, healthRes, adaptiveRes, futuresRes] = await Promise.all([
        fetch(`/api/v1/signals/performance?agent=all&regime=all&min_trades=${minTrades}&sort_by=${sortBy}&sort_dir=${sortDir}&limit=50`),
        fetch(`/api/v1/signals/cross_agent?min_trades=5`),
        fetch("/api/v1/signals/updater/state"),
        fetch("/api/v1/signals/catalog"),
        fetch("/api/v1/signals/agent_health"),
        fetch("/api/v1/signals/adaptive-engine"),
        fetch("/api/v1/signals/adaptive-engine/futures"),
      ]);
      if (perfRes.ok)    setPerfData(await perfRes.json() as PerformanceResponse);
      if (crossRes.ok)   setCrossData(await crossRes.json() as CrossResponse);
      if (stateRes.ok)   setUpdaterState(await stateRes.json() as UpdaterState);
      if (catalogRes.ok) setCatalogData(await catalogRes.json() as CatalogResponse);
      if (healthRes.ok)  setAgentHealth(await healthRes.json() as AgentHealthData);
      if (adaptiveRes.ok) setAdaptiveEngine(await adaptiveRes.json() as AdaptiveEngineData);
      if (futuresRes.ok) setFuturesEngine(await futuresRes.json() as FuturesAdaptiveEngineData);
    } catch { /* stale */ }
    finally { if (!silent) setLoading(false); }
  }, [minTrades, sortBy, sortDir]);

  const fetchRegime = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/signals/regime_heatmap?limit=30");
      if (r.ok) setRegimeData(await r.json() as RegimeResponse);
    } catch { /* stale */ }
  }, []);

  const fetchRejections = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/signals/rejections?hours=24&limit=100");
      if (r.ok) {
        const d = await r.json() as { rejections: RejectionRow[] };
        setRejectionsData(d.rejections ?? []);
      }
    } catch { /* stale */ }
  }, []);

  const fetchImprovements = useCallback(async () => {
    try {
      const [wRes, rRes] = await Promise.all([
        fetch("/api/v1/signals/performance?agent=all&regime=all&min_trades=3&sort_by=weight&sort_dir=desc&limit=100"),
        fetch("/api/v1/predictive/signal_review"),
      ]);
      if (wRes.ok) setWeightPerf(await wRes.json() as PerformanceResponse);
      if (rRes.ok) setReviewData(await rRes.json() as ReviewData);
    } catch { /* stale */ }
  }, []);

  const fetchPredictive = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/predictive/hit_rate?hours=168");
      if (r.ok) {
        const d = await r.json() as { by_agent: PredictiveHitRow[] };
        setPredictiveData(d.by_agent ?? []);
      }
    } catch { /* stale */ }
  }, []);

  useEffect(() => {
    if (subTab === "regime"       && !regimeData)     void fetchRegime();
    if (subTab === "rejections"   && !rejectionsData) void fetchRejections();
    if (subTab === "predictive"   && !predictiveData) void fetchPredictive();
    if (subTab === "improvements" && !weightPerf)     void fetchImprovements();
  }, [subTab, regimeData, rejectionsData, predictiveData, weightPerf, fetchRegime, fetchRejections, fetchPredictive, fetchImprovements]);

  useEffect(() => { void fetchAll(); }, [fetchAll]);

  const handleForce = async () => {
    setForceMsg("Memperbarui...");
    try {
      const r = await fetch("/api/v1/signals/updater/run", { method: "POST" });
      if (r.ok) {
        const d = await r.json() as { updated: Record<string, number | string> };
        setForceMsg(`Selesai: SPOT=${d.updated.spot} · Futures=${d.updated.futures} · Cross=${d.updated.cross}`);
        void fetchAll(true);
      }
    } catch { setForceMsg("Error — coba lagi"); }
    setTimeout(() => setForceMsg(null), 5000);
  };

  const allSignals   = useMemo(() => perfData?.signals ?? [], [perfData?.signals]);
  const spotSignals  = useMemo(() => allSignals.filter(s => s.agents["opportunity_spot"]), [allSignals]);
  const futSignals   = useMemo(() => allSignals.filter(s =>
    s.agents["futures_agent1"] || s.agents["futures_agent2"] || s.agents["futures_agent3"]
  ), [allSignals]);
  const crossSignals = useMemo(() => crossData?.signals ?? [], [crossData?.signals]);

  const topSpot    = useMemo(() => spotSignals.slice(0, 3), [spotSignals]);
  const topFutures = useMemo(() => futSignals.slice(0, 3), [futSignals]);
  const topCross   = useMemo(() => crossSignals.filter(s => s.reliability === "high").slice(0, 3), [crossSignals]);

  const activeSection = SECTION_OF[subTab];
  const innerTabs = SUBTABS_OF[activeSection];
  const activeSectionMeta = SECTIONS.find(s => s.key === activeSection);
  const nav = (
    <div className="space-y-3">
      {/* Level 1 — seksi utama (kartu ber-ikon + deskripsi) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {SECTIONS.map(s => {
          const active = s.key === activeSection;
          return (
            <button key={s.key} onClick={() => setSubTab(SECTION_DEFAULT[s.key])}
              className={`text-left rounded-xl border p-3 transition-all ${active
                ? "bg-neutral-900 border-neutral-900 text-white shadow-md"
                : "bg-white border-neutral-200 text-neutral-700 hover:border-neutral-300 hover:shadow-sm"}`}>
              <p className="text-sm font-black flex items-center gap-1.5">
                <span>{s.icon}</span>{s.label}
              </p>
              <p className={`text-[10px] mt-0.5 leading-tight ${active ? "text-neutral-300" : "text-neutral-400"}`}>{s.desc}</p>
            </button>
          );
        })}
      </div>

      {/* Level 2 — sub-tab dalam seksi (hanya Signals & Analysis) */}
      {innerTabs.length > 0 && (
        <div className="flex flex-wrap gap-1 bg-neutral-100 p-1 rounded-xl w-fit">
          {innerTabs.map(t => (
            <button key={t.key} onClick={() => setSubTab(t.key)}
              className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${subTab === t.key ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500 hover:text-neutral-700"}`}>
              {t.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-5 max-w-6xl">
      {showTutorial && (
        <AdaptiveLearningTutorial
          onClose={() => setShowTutorial(false)}
          health={agentHealth}
          predictive={predictiveData}
          adaptive={adaptiveEngine}
        />
      )}

      {/* Header */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs text-neutral-400 uppercase tracking-wider font-semibold mb-1">🧠 Adaptive Learning Engine</p>
            <h1 className="text-2xl font-black mb-1">Signal Performance</h1>
            <p className="text-sm text-neutral-400">
              Setiap sinyal dilacak dari entry → close. Weight naik bila profitable, turun bila sering loss.
              Agents saling belajar via cross-agent blending. Predictive log mengukur akurasi di luar paper trade.
            </p>
            {forceMsg && (
              <p className="mt-2 text-xs text-teal-300 font-semibold">{forceMsg}</p>
            )}
          </div>
          <button
            onClick={() => setShowTutorial(true)}
            className="shrink-0 w-8 h-8 rounded-full bg-white/10 hover:bg-white/20 text-white text-sm font-black transition-colors flex items-center justify-center"
            title="Cara kerja adaptive learning">
            ?
          </button>
        </div>
      </div>

      {nav}

      {activeSectionMeta && (
        <div className="flex items-baseline gap-2 px-1">
          <h2 className="text-lg font-black text-neutral-800">{activeSectionMeta.icon} {activeSectionMeta.label}</h2>
          <span className="text-xs text-neutral-400">{activeSectionMeta.desc}</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-neutral-400 gap-2">
          <div className="w-5 h-5 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
          Memuat data sinyal...
        </div>
      ) : (
        <>
          {/* ── OVERVIEW ─────────────────────────────────────────────────── */}
          {subTab === "overview" && (
            <div className="space-y-5">
              {/* U1 — Ringkasan awam: 3 pertanyaan kunci dijawab langsung */}
              <PlainSummaryBanner health={agentHealth} futures={futuresEngine} />

              {/* Agent health cards */}
              <AgentHealthCards health={agentHealth} />

              {/* F6: dua engine sejajar — konsep pipeline yang sama, dua market */}
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <AdaptiveEnginePanel data={adaptiveEngine} compact />
                <FuturesAdaptiveEnginePanel data={futuresEngine} compact />
              </div>

              {/* Summary strip */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: "Total Signal Keys", val: perfData?.meta.total ?? 0,    color: "text-neutral-800" },
                  { label: "SPOT Signals",       val: spotSignals.length,            color: "text-teal-600"    },
                  { label: "Futures Signals",    val: futSignals.length,             color: "text-blue-600"    },
                  { label: "Cross-Agent",        val: crossSignals.length,           color: "text-purple-600"  },
                ].map(x => (
                  <div key={x.label} className="bg-white border border-neutral-200 rounded-2xl p-4 text-center">
                    <p className={`text-3xl font-black ${x.color}`}>{x.val}</p>
                    <p className="text-[10px] text-neutral-400 mt-0.5 font-semibold uppercase">{x.label}</p>
                  </div>
                ))}
              </div>

              {/* Top signals preview */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {[
                  { title: "🎯 Top SPOT Signals",     signals: topSpot,    agentKey: "opportunity_spot" },
                  { title: "⚡ Top Futures Signals",  signals: topFutures, agentKey: "futures_agent2"  },
                  { title: "🔗 Proven Cross-Agent",   signals: topCross,   agentKey: "cross"           },
                ].map(col => (
                  <div key={col.title} className="bg-white border border-neutral-200 rounded-2xl p-4">
                    <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider mb-3">{col.title}</p>
                    {col.signals.length === 0 ? (
                      <p className="text-xs text-neutral-400 text-center py-4">Belum ada data</p>
                    ) : col.agentKey === "cross" ? (
                      <div className="space-y-2">
                        {(col.signals as CrossSignalRow[]).map(s => (
                          <div key={s.signal_key} className="flex items-center justify-between py-1.5 border-b border-neutral-50 last:border-0">
                            <div className="flex-1 min-w-0">
                              <p className="text-[11px] font-semibold text-neutral-700 truncate font-mono">
                                {catalogData?.catalog?.[s.signal_key]?.label ?? s.signal_key.replace(/_/g, " ")}
                              </p>
                              <p className="text-[9px] text-neutral-400">{s.agent_count} agen · {s.cross_total} trades</p>
                            </div>
                            <WinRateBadge rate={s.cross_win_rate} total={s.cross_total} />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {(col.signals as SignalRow[]).map(s => {
                          const d = s.agents[col.agentKey] ?? Object.values(s.agents)[0];
                          if (!d) return null;
                          return (
                            <div key={s.signal_key} className="flex items-center justify-between py-1.5 border-b border-neutral-50 last:border-0">
                              <div className="flex-1 min-w-0">
                                <p className="text-[11px] font-semibold text-neutral-700 truncate font-mono">
                                  {catalogData?.catalog?.[s.signal_key]?.label ?? s.signal_key.replace(/_/g, " ")}
                                </p>
                                <WeightBar weight={d.weight} />
                              </div>
                              <WinRateBadge rate={d.win_rate} total={d.total} />
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Learning loop status */}
              <LearningLoopStatus state={updaterState} onForce={handleForce} />
            </div>
          )}

          {subTab === "adaptive" && (
            <div className="space-y-4">
              <div className="bg-teal-50 border border-teal-100 rounded-2xl p-4">
                <p className="font-bold text-teal-800 mb-1">Adaptive Learning Engine — kondisi live</p>
                <p className="text-xs text-teal-700">
                  Engine memakai realized net outcome, canonical signal IDs, cross-agent evidence,
                  Wilson lower-confidence probability, capped Kelly sizing, dan calibrated challenger.
                  Model hanya naik dari shadow → canary → champion setelah seluruh gate lulus.
                </p>
              </div>
              {/* P1 — pipeline live per market */}
              <PipelineLive spot={adaptiveEngine} futures={futuresEngine} health={agentHealth} updater={updaterState} />
              <AdaptiveEnginePanel data={adaptiveEngine} />
              {/* F6: engine FUTURES sejajar — pola sama, biaya NET true-cost + veto-only */}
              <FuturesAdaptiveEnginePanel data={futuresEngine} />
              {/* U4 — kamus istilah untuk pembaca non-teknis */}
              <GlossaryBox />
              <LearningLoopStatus state={updaterState} onForce={handleForce} />
            </div>
          )}

          {/* ── SPOT ─────────────────────────────────────────────────────── */}
          {subTab === "spot" && (
            <div className="space-y-4">
              <div className="bg-teal-50 border border-teal-100 rounded-2xl p-4">
                <p className="font-bold text-teal-800 mb-1">🎯 Bobot Sinyal SPOT</p>
                <p className="text-xs text-teal-600">
                  <strong>Untuk apa?</strong> Melihat sinyal mana yang dipercaya sistem di market SPOT.
                  Weight ×&gt;1.00 = terbukti profit, pengaruhnya diperbesar; ×&lt;1.00 = sering rugi, dikurangi.
                  Bobot diperbarui otomatis setiap trade selesai. Win Rate = persen trade menang; Avg PnL% = rata-rata untung/rugi.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs text-neutral-500">{spotSignals.length} sinyal · min {minTrades} trades</span>
                <div className="flex bg-neutral-100 rounded-xl p-1 gap-0.5 ml-auto">
                  {[3, 5, 10].map(n => (
                    <button key={n} onClick={() => setMinTrades(n)}
                      className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${minTrades === n ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500"}`}>
                      ≥{n}
                    </button>
                  ))}
                </div>
              </div>
              <SignalTable signals={spotSignals} agentKey="opportunity_spot"
                sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir}
                catalog={catalogData} />
            </div>
          )}

          {/* ── FUTURES ──────────────────────────────────────────────────── */}
          {subTab === "futures" && (
            <div className="space-y-4">
              <div className="bg-blue-50 border border-blue-100 rounded-2xl p-4">
                <p className="font-bold text-blue-800 mb-1">⚡ Bobot Sinyal FUTURES</p>
                <p className="text-xs text-blue-600">
                  <strong>Untuk apa?</strong> Sama seperti SPOT, tapi per agen futures — pilih agen di bawah
                  untuk melihat bobot sinyalnya masing-masing (tiap agen berburu tipe peluang berbeda).
                  Weight ×&gt;1.00 = dipercaya, ×&lt;1.00 = dikurangi; di bawah ×0.80 dengan ≥10 trades sinyal otomatis DIVETO saat learning aktif.
                  Detail mesin belajarnya ada di seksi Engine.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 items-center">
                <div className="flex gap-1 bg-neutral-100 p-1 rounded-xl">
                  {AGENT_TABS.filter(a => a.key !== "opportunity_spot").map(a => (
                    <button key={a.key} onClick={() => setAgentFilter(a.key)}
                      className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${agentFilter === a.key ? `bg-white shadow-sm ${a.color}` : "text-neutral-500 hover:text-neutral-700"}`}>
                      {a.label}
                    </button>
                  ))}
                </div>
                <div className="flex bg-neutral-100 rounded-xl p-1 gap-0.5 ml-auto">
                  {[3, 5, 10].map(n => (
                    <button key={n} onClick={() => setMinTrades(n)}
                      className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${minTrades === n ? "bg-white text-neutral-900 shadow-sm" : "text-neutral-500"}`}>
                      ≥{n}
                    </button>
                  ))}
                </div>
              </div>
              <SignalTable
                signals={futSignals.filter(s => s.agents[agentFilter])}
                agentKey={agentFilter}
                sortBy={sortBy} setSortBy={setSortBy} sortDir={sortDir} setSortDir={setSortDir}
                catalog={catalogData}
              />
            </div>
          )}

          {/* ── CROSS-AGENT ───────────────────────────────────────────────── */}
          {subTab === "cross" && (
            <div className="space-y-4">
              <div className="bg-purple-50 border border-purple-100 rounded-2xl p-4 text-sm text-purple-800">
                <p className="font-bold mb-1">🔗 Bobot Sinyal Cross-Agent</p>
                <p className="text-xs text-purple-600">
                  <strong>Untuk apa?</strong> Melihat sinyal yang terbukti profit di <strong>lebih dari satu agen</strong> —
                  bukti terkuat bahwa sinyal itu benar-benar bagus, bukan kebetulan.
                  Weight gabungan ini dicampur 30% ke bobot tiap agen (70% bobot agen sendiri).
                  Hanya muncul jika total ≥ 10 trades gabungan.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 items-center">
                <span className="text-xs text-neutral-500">{crossSignals.length} sinyal · gabungan ≥ 10 trades</span>
              </div>
              <CrossAgentTable signals={crossSignals} />
            </div>
          )}

          {/* ── PERBAIKAN LIVE (P4) ───────────────────────────────────────── */}
          {subTab === "improvements" && (
            <div className="space-y-4">
              <div className="bg-green-50 border border-green-100 rounded-2xl p-4">
                <p className="font-bold text-green-800 mb-1">🔧 Perbaikan Live — apa yang sedang diperbaiki sistem sekarang</p>
                <p className="text-xs text-green-700">
                  <strong>Untuk apa?</strong> Melihat langsung hasil belajar sistem untuk SPOT dan FUTURES:
                  sinyal mana yang bobotnya sedang DINAIKKAN (terbukti profit), mana yang DITURUNKAN atau
                  DIVETO (sering rugi), plus pengaman yang sedang aktif (koin blacklist, lane dijeda).
                  Semua otomatis — tidak ada yang diubah manual.
                </p>
              </div>
              <ImprovementsTab weightPerf={weightPerf} health={agentHealth}
                futures={futuresEngine} review={reviewData} catalog={catalogData} />
            </div>
          )}

          {/* ── REGIME HEATMAP ────────────────────────────────────────────── */}
          {subTab === "regime" && (
            <div className="space-y-4">
              <div className="bg-blue-50 border border-blue-100 rounded-2xl p-4">
                <p className="font-bold text-blue-800 mb-1">🌡 Regime — sinyal mana yang cocok di kondisi pasar apa</p>
                <p className="text-xs text-blue-600">
                  <strong>Untuk apa?</strong> Sinyal yang sama bisa bagus saat pasar naik tapi buruk saat pasar bergejolak.
                  Tabel ini melacak bobot tiap sinyal per kondisi pasar (naik / turun / datar / bergejolak) —
                  sistem otomatis mengecilkan pengaruh sinyal yang buruk di kondisi pasar SAAT INI.
                  Hijau = bagus di kondisi itu, merah = buruk. Data muncul setelah ≥3 trade per kondisi selesai.
                </p>
              </div>
              <RegimeHeatmap regimeData={regimeData} />
            </div>
          )}

          {/* ── FORMULAS ──────────────────────────────────────────────────── */}
          {subTab === "formulas" && (
            <div className="space-y-4">
              <div className="bg-teal-50 border border-teal-100 rounded-2xl p-4">
                <p className="font-bold text-teal-800 mb-1">🔬 Formulas — kamus semua sinyal teknikal</p>
                <p className="text-xs text-teal-600">
                  <strong>Untuk apa?</strong> Kalau di tab lain Anda menemukan nama sinyal yang tidak dimengerti,
                  cari artinya di sini: apa yang diukur sinyal itu, agen mana yang memakainya, dan berapa
                  poin maksimal sumbangannya ke skor. Ini referensi, bukan data live.
                </p>
              </div>
              <FormulasTab catalog={catalogData} />
            </div>
          )}

          {/* ── REJECTIONS ────────────────────────────────────────────────── */}
          {subTab === "rejections" && (
            <div className="space-y-4">
              <div className="bg-red-50 border border-red-100 rounded-2xl p-4">
                <p className="font-bold text-red-800 mb-1">🚫 Rejections — koin yang HAMPIR dibuka (24 jam terakhir)</p>
                <p className="text-xs text-red-600">
                  <strong>Untuk apa?</strong> Melihat kandidat yang skornya tidak cukup untuk dibuka.
                  Kolom &quot;Gap&quot; = kurang berapa poin lagi — makin kecil, makin nyaris.
                  Kalau banyak koin bagus yang nyaris terus, itu tanda ambang skor mungkin terlalu ketat.
                </p>
              </div>
              {!rejectionsData ? (
                <div className="text-center py-10 text-neutral-400 text-sm">Memuat...</div>
              ) : rejectionsData.length === 0 ? (
                <div className="text-center py-10 text-neutral-400 text-sm">Tidak ada rejection dalam 24h terakhir</div>
              ) : (
                <div className="overflow-hidden rounded-xl border border-neutral-200">
                  <div className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-3 px-4 py-2 bg-neutral-50 border-b border-neutral-200 text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
                    <span>Symbol / Agent</span>
                    <span className="text-right">Score</span>
                    <span className="text-right">Gap</span>
                    <span>Regime</span>
                    <span>Waktu</span>
                  </div>
                  <div className="divide-y divide-neutral-100 max-h-[500px] overflow-y-auto">
                    {rejectionsData.map(r => {
                      const gap = r.threshold - r.score;
                      const gapColor = gap < 5 ? "text-yellow-600" : gap < 10 ? "text-orange-500" : "text-red-500";
                      // weak_signals is string[] from API
                      const weakList = Array.isArray(r.weak_signals)
                        ? r.weak_signals.slice(0, 2).join(", ")
                        : (r.weak_signals ?? "");
                      return (
                        <div key={r.id} className="grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-3 px-4 py-2.5 items-start hover:bg-neutral-50">
                          <div>
                            <p className="text-xs font-bold text-neutral-800">
                              {r.symbol}
                              <span className={`ml-1.5 text-[9px] font-semibold ${r.direction === "LONG" ? "text-green-600" : "text-red-500"}`}>
                                {r.direction}
                              </span>
                            </p>
                            <p className="text-[9px] text-neutral-400">{r.agent.replace("futures_", "")} · {weakList}</p>
                          </div>
                          <p className="text-xs font-mono tabular-nums text-neutral-600 text-right">{r.score.toFixed(1)}</p>
                          <p className={`text-xs font-bold tabular-nums text-right ${gapColor}`}>-{gap.toFixed(1)}</p>
                          <span className="text-[9px] bg-neutral-100 text-neutral-500 px-1.5 py-0.5 rounded-full self-start">{r.regime}</span>
                          <p className="text-[9px] text-neutral-400 tabular-nums">{new Date(r.rejected_at * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── PREDICTIVE ────────────────────────────────────────────────── */}
          {subTab === "predictive" && (
            <div className="space-y-4">
              <div className="bg-indigo-50 border border-indigo-100 rounded-2xl p-4">
                <p className="font-bold text-indigo-800 mb-1">🔮 Predictive — rapor akurasi tebakan agen (7 hari)</p>
                <p className="text-xs text-indigo-600">
                  <strong>Untuk apa?</strong> Mengukur apakah agen benar-benar pintar menebak arah harga.
                  Setiap kandidat dicatat saat scan, lalu 4 jam & 24 jam kemudian dicek: apakah harga
                  benar bergerak sesuai prediksi (minimal 1.5% dalam 4 jam / 3% dalam 24 jam)?
                  Ini menilai SEMUA prediksi — termasuk yang tidak jadi dibuka sebagai trade.
                </p>
              </div>
              <PredictivePanel data={predictiveData} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
