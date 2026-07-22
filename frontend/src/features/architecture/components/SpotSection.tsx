"use client";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge, LiveBadge, SectionTitle, SourceBadge } from "./primitives";
import {
  SPOT_LANES,
  SPOT_FEEDERS,
  SPOT_SIGNALS,
  SPOT_DIRECTION_GATE,
  SPOT_MONITOR_LAYERS,
  SYSTEM_OVERVIEW,
} from "../data";
import { useAgentConfig } from "../hooks/useAgentConfig";
import { useAgentConfigDbKeys } from "../hooks/useAgentConfigDbKeys";

// ─── UNIVERSE OVERVIEW ────────────────────────────────────────────────────────
function UniverseBar() {
  const { data, loading } = useAgentConfig();
  const dbKeys = useAgentConfigDbKeys();
  const live = data?.spot;
  const o = SYSTEM_OVERVIEW.spot;

  const vols = live?.min_volume;
  const volRange = vols
    ? `$${Math.min(...Object.values(vols)) >= 1000 ? `${(Math.min(...Object.values(vols)) / 1000).toFixed(0)}K` : Math.min(...Object.values(vols))} – $${(Math.max(...Object.values(vols)) / 1_000_000).toFixed(0)}M`
    : o.minVolume;

  const stats: { label: string; val: string; dbKey?: string }[] = [
    { label: "Scan Interval",     val: live?.scan_interval_sec != null ? `${Math.round(live.scan_interval_sec / 60)} menit` : o.scanInterval },
    { label: "Monitor",           val: live?.monitor_interval_sec != null ? `${live.monitor_interval_sec} detik` : o.monitorInterval },
    { label: "Fastpass BigMover", val: live?.fastpass?.bigmover_interval_sec != null ? `${live.fastpass.bigmover_interval_sec} detik` : o.fastpassInterval.replace(" (BigMover)", "") },
    { label: "Vol Range",         val: volRange, dbKey: "spot.min_quote_volume" },
    { label: "Min Score",         val: live ? String(live.score_thresholds?.accumulation?.min ?? o.minScore) : String(o.minScore), dbKey: "spot.min_score" },
    { label: "Auto-Open",         val: live ? String(live.score_thresholds?.accumulation?.auto ?? o.autoOpenScore) : String(o.autoOpenScore), dbKey: "spot.auto_open_score" },
    { label: "R:R Min",           val: `≥ ${o.rrMin}` },
    { label: "Max Open/Cycle",    val: live ? String(live.quota?.max_opens_per_cycle ?? o.maxOpensCycle) : String(o.maxOpensCycle), dbKey: "spot.max_opens_per_cycle" },
  ];
  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[10px] font-bold uppercase tracking-wider text-neutral-400">System Overview</p>
        <LiveBadge live={!!live} loading={loading} />
      </div>
      <div className="grid grid-cols-4 md:grid-cols-8 gap-2">
        {stats.map(s => (
          <div key={s.label} className="bg-neutral-50 border rounded-xl px-3 py-2 text-center">
            <p className="text-[10px] text-neutral-500 font-medium flex items-center justify-center">
              {s.label}
              {s.dbKey && <SourceBadge dbKey={s.dbKey} dbKeys={dbKeys} />}
            </p>
            <p className="text-xs font-bold text-teal-700 mt-0.5">{s.val}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// PLAN_v5 Group C7 — DB key per lane (matches agent_config_defaults.py seed keys).
// PLAN_SPOT_LANES S1: entri "weekly" dihapus — ia feeder universe, bukan lane,
// dan tidak punya gerbang skor sendiri di scanner.py.
const LANE_DB_KEYS: Record<string, { vol: string; min: string; auto: string }> = {
  accumulation: { vol: "spot.min_quote_volume",      min: "spot.min_score",             auto: "spot.auto_open_score" },
  breakout:     { vol: "spot.breakout_min_volume",   min: "spot.breakout_min_score",    auto: "spot.breakout_auto_score" },
  bigmover:     { vol: "spot.bigmover_min_volume",   min: "spot.bigmover_min_score",    auto: "spot.bigmover_auto_score" },
  early_radar:  { vol: "spot.early_radar_min_volume", min: "spot.early_radar_min_score", auto: "spot.early_radar_auto_score" },
};

// ─── 4 LANES ─────────────────────────────────────────────────────────────────
function LanesSection() {
  const [active, setActive] = useState(SPOT_LANES[0].key);
  const lane = SPOT_LANES.find(l => l.key === active)!;
  const { data } = useAgentConfig();
  const dbKeys = useAgentConfigDbKeys();
  const live = data?.spot;
  const laneDbKeys = LANE_DB_KEYS[lane.key];

  const liveMinVol   = live?.min_volume?.[lane.key];
  const liveScore    = live?.score_thresholds?.[lane.key];
  const minScore     = liveScore?.min ?? lane.minScore;
  const autoScore    = liveScore?.auto ?? lane.autoScore;
  const minVolumeStr = liveMinVol
    ? liveMinVol >= 1_000_000 ? `$${(liveMinVol / 1_000_000).toFixed(1).replace(".0", "")}M` : `$${(liveMinVol / 1000).toFixed(0)}K`
    : lane.minVolume;

  return (
    <div className="mb-6">
      <SectionTitle icon="🛣" title="4 Scanning Lanes" sub="Setiap lane punya universe, trigger, alert_type, dan SL/TP sendiri" />
      <div className="flex gap-2 mb-4 flex-wrap">
        {SPOT_LANES.map(l => (
          <button key={l.key} onClick={() => setActive(l.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-bold transition-all ${
              active === l.key
                ? "bg-teal-600 text-white border-teal-600"
                : "bg-white border-neutral-200 text-neutral-600 hover:border-teal-300"
            }`}>
            <span>{l.emoji}</span> {l.label}
          </button>
        ))}
      </div>

      <div className={`rounded-xl border p-4 ${lane.color}`}>
        <div className="flex items-start justify-between gap-4 mb-3">
          <div>
            <p className="text-base font-bold flex items-center gap-2">{lane.emoji} {lane.label}</p>
            <p className="text-xs mt-1 opacity-80 max-w-xl">{lane.desc}</p>
          </div>
          <div className="text-right shrink-0 space-y-1">
            <span className="inline-flex items-center">
              <Badge label={`Min Score: ${minScore}`} color={lane.badgeColor} />
              {laneDbKeys && <SourceBadge dbKey={laneDbKeys.min} dbKeys={dbKeys} />}
            </span>
            <div />
            <span className="inline-flex items-center">
              <Badge label={`Auto-Open: ${autoScore}`} color={lane.badgeColor} />
              {laneDbKeys && <SourceBadge dbKey={laneDbKeys.auto} dbKeys={dbKeys} />}
            </span>
          </div>
        </div>

        <div className="grid md:grid-cols-2 gap-3">
          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <InfoRow label="Min Volume" val={minVolumeStr} />
              {laneDbKeys && <SourceBadge dbKey={laneDbKeys.vol} dbKeys={dbKeys} />}
            </div>
            <InfoRow label="Trigger" val={lane.trigger} />
            <InfoRow label="SL Method" val={lane.slMethod} />
            <InfoRow label="SL Range" val={lane.slRange} />
            <InfoRow label="R:R Min" val={`≥ ${lane.rrMin}`} />
            <InfoRow label="Max Age" val={lane.maxAge} />
            {lane.tp1Partial && <InfoRow label="TP1 Action" val={lane.tp1Partial} />}
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider opacity-60 mb-2">Take Profit Levels</p>
            {lane.tp.map((t, i) => (
              <div key={i} className="flex items-start gap-2 mb-1.5">
                <span className="shrink-0 w-6 h-6 rounded-full bg-white/60 flex items-center justify-center text-[10px] font-bold">{i + 1}</span>
                <p className="text-xs leading-relaxed">{t}</p>
              </div>
            ))}
            {lane.extras && (
              <div className="mt-3 pt-3 border-t border-current/10 space-y-1">
                {lane.extras.map(e => (
                  <p key={e} className="text-[11px] opacity-70 flex items-start gap-1">
                    <span className="text-teal-600 shrink-0">›</span> {e}
                  </p>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <FeedersSection />
    </div>
  );
}

// ─── UNIVERSE FEEDERS ────────────────────────────────────────────────────────
// PLAN_SPOT_LANES S1: sebelumnya "Weekly Momentum" berdiri sejajar 4 lane di atas
// lengkap dengan minScore/autoScore/rrMin — angka yang tidak pernah dibaca kode.
// Ia (dan supplement momentum 24h) hanya memperluas pool kandidat.
function FeedersSection() {
  return (
    <div className="mt-4 rounded-xl border border-dashed border-neutral-300 bg-neutral-50 p-4">
      <p className="text-xs font-bold text-neutral-700 mb-1">🍽 Universe Feeder — bukan lane</p>
      <p className="text-[11px] text-neutral-500 mb-3 max-w-2xl">
        Keduanya hanya <strong>menambah koin</strong> ke pool kandidat; penilaiannya tetap
        dilakukan salah satu dari 4 lane di atas. Karena itu mereka tidak punya
        <code className="mx-1 px-1 bg-white rounded border border-neutral-200">alert_type</code>
        sendiri dan tidak akan pernah muncul sebagai lane tersendiri di halaman History.
      </p>
      <div className="grid md:grid-cols-2 gap-3">
        {SPOT_FEEDERS.map(f => (
          <div key={f.key} className="rounded-lg bg-white border border-neutral-200 p-3">
            <p className="text-xs font-bold flex items-center gap-1.5 mb-1">
              <span>{f.emoji}</span> {f.label}
              <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${f.badgeColor}`}>feeder</span>
            </p>
            <p className="text-[11px] text-neutral-600 leading-relaxed mb-2">{f.desc}</p>
            <InfoRow label="Trigger" val={f.trigger} />
            <InfoRow label="Biaya" val={f.cost} />
            <div className="mt-2 space-y-0.5">
              {f.extras.map(e => (
                <p key={e} className="text-[10px] text-neutral-500 flex items-start gap-1">
                  <span className="text-teal-600 shrink-0">›</span> {e}
                </p>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function InfoRow({ label, val }: { label: string; val: string }) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="shrink-0 font-semibold opacity-60 w-24">{label}</span>
      <span className="font-medium">{val}</span>
    </div>
  );
}

// ─── CARA POSISI DIBUKA (auto-open per lane + force-open) ─────────────────────
// PLAN_v8 P1 — transparansi. Menjawab kebingungan "kenapa score 65 open?":
// tiap lane punya auto-open threshold sendiri (BigMover 65, Breakout 75,
// Accumulation/Early/Weekly 85). Plus jalur manual "Force-Open" yang bypass gate.
function OpenLogicSection() {
  const { data } = useAgentConfig();
  const live = data?.spot;

  const rows = SPOT_LANES.map(l => {
    const t = live?.score_thresholds?.[l.key];
    return { emoji: l.emoji, label: l.label, min: t?.min ?? l.minScore, auto: t?.auto ?? l.autoScore };
  });

  return (
    <div>
      <SectionTitle icon="🚪" title="Cara Posisi Dibuka" sub="Dua jalur: AUTO (skor lolos threshold per-lane) atau FORCE-OPEN (manual, bypass gate)" />

      {/* Jalur 1: AUTO per-lane threshold */}
      <div className="rounded-xl border border-neutral-200 overflow-hidden mb-4">
        <div className="bg-teal-50 px-4 py-2 border-b border-neutral-200">
          <p className="text-xs font-bold text-teal-800">1️⃣ Auto-Open — threshold berbeda per lane</p>
          <p className="text-[11px] text-teal-700 mt-0.5">
            Skor yang sama bisa auto-open di satu lane tapi tidak di lane lain. Ini kenapa score <b>65 bisa langsung open</b> lewat BigMover, padahal Accumulation butuh 85.
          </p>
        </div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-neutral-400 border-b border-neutral-100">
              <th className="text-left font-semibold px-4 py-1.5">Lane</th>
              <th className="text-right font-semibold px-4 py-1.5">Min Score (masuk radar)</th>
              <th className="text-right font-semibold px-4 py-1.5">Auto-Open (langsung buka)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.label} className="border-b border-neutral-50 last:border-0">
                <td className="px-4 py-2 font-bold">{r.emoji} {r.label}</td>
                <td className="px-4 py-2 text-right tabular-nums text-neutral-600">≥ {r.min}</td>
                <td className="px-4 py-2 text-right tabular-nums font-black text-teal-700">≥ {r.auto}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Jalur 2: FORCE-OPEN manual */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
        <p className="text-xs font-bold text-amber-800 mb-1">2️⃣🖐 Force-Open — override manual dari UI</p>
        <p className="text-[11px] text-amber-700 leading-relaxed mb-2">
          Tombol manual (<code className="bg-white/60 px-1 rounded">POST /opportunity/trade</code> dengan <code className="bg-white/60 px-1 rounded">force_open=true</code>) membuka posisi <b>tanpa menunggu skor lolos threshold</b>. Dipakai untuk eksekusi keyakinan manual di luar sinyal agent.
        </p>
        <div className="grid md:grid-cols-3 gap-2">
          <div className="bg-white/70 rounded-lg px-3 py-2">
            <p className="text-[10px] font-bold text-amber-600 uppercase">Rate limit</p>
            <p className="text-xs font-semibold text-neutral-700">5 / jam / sesi</p>
          </div>
          <div className="bg-white/70 rounded-lg px-3 py-2">
            <p className="text-[10px] font-bold text-amber-600 uppercase">Penanda</p>
            <p className="text-xs font-semibold text-neutral-700"><code>manual:true</code> di signals_json</p>
          </div>
          <div className="bg-white/70 rounded-lg px-3 py-2">
            <p className="text-[10px] font-bold text-amber-600 uppercase">Terlihat sebagai</p>
            <p className="text-xs font-semibold text-neutral-700">Badge 🖐 Manual (dashboard & history)</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── 12 SIGNALS ───────────────────────────────────────────────────────────────
function SignalsSection() {
  const [active, setActive] = useState(SPOT_SIGNALS[0].id);
  const sig = SPOT_SIGNALS.find(s => s.id === active)!;

  const catColor: Record<string, string> = {
    setup:    "bg-blue-100 text-blue-700",
    timing:   "bg-orange-100 text-orange-700",
    market:   "bg-purple-100 text-purple-700",
    momentum: "bg-amber-100 text-amber-700",
    trend:    "bg-teal-100 text-teal-700",
  };

  return (
    <div className="mb-6">
      <SectionTitle icon="🔭" title="12 Scoring Signals" sub="Akumulasi poin dari 12 sinyal — threshold 65 untuk open, 85 untuk auto-open" />

      {/* Direction Gate note */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 mb-4">
        <p className="text-xs font-bold text-amber-800 mb-1">⚡ Direction Gate — wajib untuk auto-open & BB Squeeze full points</p>
        <p className="text-[11px] text-amber-700">
          {SPOT_DIRECTION_GATE.conditions.join(" ")}
        </p>
      </div>

      {/* Signal selector */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-1.5 mb-4">
        {SPOT_SIGNALS.map(s => (
          <button key={s.id} onClick={() => setActive(s.id)}
            className={`flex flex-col items-center gap-0.5 px-2 py-2 rounded-lg border text-center transition-all ${
              active === s.id
                ? "bg-teal-600 text-white border-teal-600"
                : "bg-white border-neutral-200 text-neutral-600 hover:border-teal-300"
            }`}>
            <span className="text-base">{s.emoji}</span>
            <span className="text-[9px] font-bold leading-tight">{s.name.split(" ").slice(0, 2).join(" ")}</span>
            <span className={`text-[9px] px-1 rounded-full font-bold ${active === s.id ? "bg-white/20 text-white" : "bg-teal-50 text-teal-700"}`}>
              +{s.maxPts}
            </span>
          </button>
        ))}
      </div>

      {/* Signal detail */}
      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-2xl">{sig.emoji}</span>
            <div>
              <p className="font-bold text-neutral-800">{sig.name}</p>
              <div className="flex gap-1 mt-0.5">
                <Badge label={`Max ${sig.maxPts} pts`} color="bg-teal-100 text-teal-700" />
                <Badge label={sig.category} color={catColor[sig.category] ?? "bg-neutral-100 text-neutral-600"} />
              </div>
            </div>
          </div>
          <pre className="bg-neutral-900 text-green-400 text-[10px] font-mono p-3 rounded-lg overflow-x-auto leading-relaxed whitespace-pre-wrap mb-3">
            {sig.formula}
          </pre>
        </div>
        <div className="space-y-3">
          <div>
            <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wide mb-2">Scoring</p>
            <div className="space-y-1.5">
              {sig.scoring.map((sc, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="shrink-0 w-10 font-black text-teal-600 text-right">+{sc.pts}</span>
                  <span className="text-neutral-700">{sc.cond}</span>
                  {sc.note && <Badge label={sc.note} color="bg-blue-50 text-blue-600" />}
                </div>
              ))}
              {sig.penalties?.map((p, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="shrink-0 w-10 font-black text-red-500 text-right">{p.pts}</span>
                  <span className="text-neutral-700">{p.cond}</span>
                  {p.note && <Badge label={p.note} color="bg-red-50 text-red-600" />}
                </div>
              ))}
            </div>
          </div>
          <div className="bg-neutral-50 rounded-xl p-3 border">
            <p className="text-[10px] font-bold text-neutral-500 mb-1">💡 Kenapa works?</p>
            <p className="text-[11px] text-neutral-700 leading-relaxed">{sig.why}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── MONITOR LAYERS ───────────────────────────────────────────────────────────
function MonitorSection() {
  const [open, setOpen] = useState<string | null>("L1");
  return (
    <div>
      <SectionTitle icon="👁" title="Monitor — 6 Exit Layers" sub="Berjalan setiap 60s (+ wick detection 1m). Diproses berurutan L0 → L4, termasuk L2.5 Rotation (tukar posisi stagnan)." />
      <div className="space-y-2">
        {SPOT_MONITOR_LAYERS.map(layer => (
          <div key={layer.layer} className={`rounded-xl border overflow-hidden ${layer.color}`}>
            <button className="w-full flex items-center gap-3 px-4 py-3 text-left" onClick={() => setOpen(open === layer.layer ? null : layer.layer)}>
              <span className="text-base w-7 shrink-0">{layer.emoji}</span>
              <div className="flex-1">
                <p className="text-xs font-bold text-neutral-800">{layer.layer} — {layer.title}</p>
                <p className="text-[11px] text-neutral-500 mt-0.5">{layer.desc}</p>
              </div>
              <span className="text-neutral-400 text-sm">{open === layer.layer ? "▲" : "▼"}</span>
            </button>
            {open === layer.layer && (
              <div className="px-4 pb-4 pt-0 border-t border-neutral-200">
                <div className="space-y-2 mt-3">
                  {layer.closes.map((c, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <span className="shrink-0 w-2 h-2 rounded-full bg-neutral-400 mt-1.5" />
                      <div>
                        <p className="text-xs text-neutral-700">{c.reason}</p>
                        {c.note && <p className="text-[10px] text-neutral-500 mt-0.5">→ {c.note}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────
export function SpotSection() {
  return (
    <div className="space-y-2">
      <Card><CardContent className="pt-5"><UniverseBar /><LanesSection /></CardContent></Card>
      <Card><CardContent className="pt-5"><OpenLogicSection /></CardContent></Card>
      <Card><CardContent className="pt-5"><SignalsSection /></CardContent></Card>
      <Card><CardContent className="pt-5"><MonitorSection /></CardContent></Card>
    </div>
  );
}
