"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { fmtPrice } from "@/lib/format";
import type { SpotAsset } from "./SpotPortfolioPanel";

const STORAGE_KEY = "rebalance-targets-v1";
const GUIDE_KEY = "rebalance-guide-v1";
const SETTINGS_KEY = "rebalance-settings-v1";
const CASH = "USDT";
/** Aset di bawah nilai ini dianggap debu — tak masuk kalkulasi bobot. */
const DUST_USDT = 1;
/** Cadangan bila filter bursa tak terbaca: minimum order Binance ≈ $5. */
const FALLBACK_MIN_ORDER = 5;
/** Fee taker SPOT Binance standar (tanpa diskon BNB). */
const FEE_RATE = 0.001;

type Targets = Record<string, number>;
type Mode = "band" | "full" | "cash";
interface Settings {
  mode: Mode;
  bandAbs: number;     // pita absolut, poin persen
  bandRel: number;     // pita relatif, % dari target
  anchor: string;      // aset jangkar (porsi minimum)
  anchorMin: number;   // porsi minimum aset jangkar, %
  extraCash: number;   // setoran baru (USDT) — mode "cash"
  lastDone: number | null;
}
const DEFAULT_SETTINGS: Settings = {
  mode: "band", bandAbs: 5, bandRel: 25, anchor: "BTC", anchorMin: 65, extraCash: 0, lastDone: null,
};
interface Filter { step_size: number; min_qty: number; min_notional: number }

function load<T extends object>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...(JSON.parse(raw) as T) } : fallback;
  } catch { return fallback; }
}
function save(key: string, v: unknown) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* storage blocked */ }
}

function fmtQty(n: number): string {
  const v = Math.abs(n);
  if (v < 0.001) return v.toFixed(6);
  if (v < 1)     return v.toFixed(4);
  if (v < 1000)  return v.toFixed(3);
  return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

/** Bulatkan KE BAWAH ke kelipatan stepSize — bursa menolak jumlah di luar kelipatan. */
function floorStep(qty: number, step: number): number {
  if (!(step > 0)) return qty;
  const decimals = Math.max(0, Math.round(-Math.log10(step)));
  const n = Math.floor(qty / step + 1e-9) * step;
  return Number(n.toFixed(decimals));
}

/**
 * Kalkulator rebalancing porsi aset Binance SPOT.
 *
 * Tiga metode baku:
 *  - Pita toleransi (aturan 5/25): hanya aset yang menyimpang lebih dari
 *    min(5 poin, 25% dari targetnya) yang ditransaksikan — menghindari biaya
 *    untuk penyimpangan kecil yang tak bermakna.
 *  - Penuh: semua aset dikembalikan tepat ke target.
 *  - Dana baru: hanya membeli aset yang kekurangan porsi dengan kas/setoran,
 *    tanpa menjual apa pun.
 * Plus aturan porsi minimum aset jangkar (bawaan BTC ≥ 65%, ditetapkan owner).
 * Jumlah koin dibulatkan ke stepSize bursa dan diperiksa terhadap minimum order;
 * fee 0,1% ikut dihitung. Murni hitung — order tetap dipasang sendiri di Binance.
 */
export function RebalanceCalculator({ assets, loading, error }: {
  assets: SpotAsset[]; loading: boolean; error: string | null;
}) {
  const [targets, setTargetsRaw] = useState<Targets>(() => (typeof window === "undefined" ? {} : load<Targets>(STORAGE_KEY, {})));
  const setTargets = useCallback((next: Targets | ((prev: Targets) => Targets)) => {
    setTargetsRaw(prev => { const v = typeof next === "function" ? next(prev) : next; save(STORAGE_KEY, v); return v; });
  }, []);
  const [settings, setSettingsRaw] = useState<Settings>(() => (typeof window === "undefined" ? DEFAULT_SETTINGS : load(SETTINGS_KEY, DEFAULT_SETTINGS)));
  const setSetting = useCallback(<K extends keyof Settings>(k: K, v: Settings[K]) => {
    setSettingsRaw(prev => { const n = { ...prev, [k]: v }; save(SETTINGS_KEY, n); return n; });
  }, []);
  const [showGuide, setShowGuideRaw] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    try { return localStorage.getItem(GUIDE_KEY) !== "closed"; } catch { return true; }
  });
  const toggleGuide = useCallback(() => {
    setShowGuideRaw(prev => {
      try { localStorage.setItem(GUIDE_KEY, prev ? "closed" : "open"); } catch { /* storage blocked */ }
      return !prev;
    });
  }, []);

  // Baris: aset non-debu + selalu satu baris kas USDT.
  const rows = useMemo(() => {
    const live = assets.filter(a => a.asset !== CASH && a.usdt_value >= DUST_USDT);
    const cash = assets.find(a => a.asset === CASH);
    const cashRow: SpotAsset = cash ?? {
      asset: CASH, total: 0, usdt_value: 0, current_price: 1, avg_buy_price: 1, pnl_percent: null, pnl_usdt: null,
    };
    return [...live.sort((a, b) => b.usdt_value - a.usdt_value), cashRow];
  }, [assets]);
  const coinsKey = useMemo(() => rows.filter(r => r.asset !== CASH).map(r => r.asset).join(","), [rows]);

  // Filter order bursa (stepSize, minimum order) per koin.
  const [filters, setFilters] = useState<Record<string, Filter>>({});
  useEffect(() => {
    if (!coinsKey) return;
    const ctrl = new AbortController();
    const symbols = coinsKey.split(",").map(a => `${a}${CASH}`).join(",");
    apiFetch(`/api/v1/market/spot-filters?symbols=${encodeURIComponent(symbols)}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : null))
      .then((d: { filters?: Record<string, Filter> } | null) => { if (d?.filters) setFilters(d.filters); })
      .catch(() => { /* tanpa filter → pakai cadangan $5 */ });
    return () => ctrl.abort();
  }, [coinsKey]);

  const extra = settings.mode === "cash" ? Math.max(0, settings.extraCash) : 0;
  const totalNow = useMemo(() => rows.reduce((s, a) => s + a.usdt_value, 0), [rows]);
  const total = totalNow + extra;     // setoran baru menambah basis

  const setTarget = useCallback((asset: string, raw: string) => {
    const n = Number(raw);
    setTargets(prev => ({ ...prev, [asset]: Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0 }));
  }, [setTargets]);

  const anchorPresent = rows.some(r => r.asset === settings.anchor);

  const applyEqual = useCallback(() => {
    // Aset jangkar dapat porsi minimumnya, sisanya dibagi rata ke koin lain; sisa pembulatan ke kas.
    const others = rows.filter(r => r.asset !== CASH && r.asset !== settings.anchor);
    const anchorPct = anchorPresent ? settings.anchorMin : 0;
    const each = others.length ? Math.floor(((100 - anchorPct) / others.length) * 10) / 10 : 0;
    const t: Targets = {};
    if (anchorPresent) t[settings.anchor] = anchorPct;
    others.forEach(c => { t[c.asset] = each; });
    t[CASH] = Math.round((100 - anchorPct - each * others.length) * 10) / 10;
    setTargets(t);
  }, [rows, settings.anchor, settings.anchorMin, anchorPresent, setTargets]);

  const applyCurrent = useCallback(() => {
    const t: Targets = {};
    rows.forEach(r => { t[r.asset] = totalNow > 0 ? Math.round((r.usdt_value / totalNow) * 1000) / 10 : 0; });
    setTargets(t);
  }, [rows, totalNow, setTargets]);

  const plan = useMemo(() => {
    const base = rows.map(r => {
      const value = r.asset === CASH ? r.usdt_value + extra : r.usdt_value;
      const curPct = totalNow > 0 ? (r.usdt_value / totalNow) * 100 : 0;
      const tgtPct = targets[r.asset] ?? 0;
      const tgtUsd = (tgtPct / 100) * total;
      const drift = curPct - tgtPct;
      const band = Math.min(settings.bandAbs, (settings.bandRel / 100) * tgtPct);
      const breach = r.asset !== CASH && (Math.abs(drift) > band
        || (r.asset === settings.anchor && curPct < settings.anchorMin));
      return { ...r, value, curPct, tgtPct, tgtUsd, drift, band, breach, rawDelta: tgtUsd - value };
    });

    // Delta mentah per metode (koin saja; kas menyerap sisanya).
    let wanted: Record<string, number> = {};
    if (settings.mode === "full") {
      base.forEach(p => { if (p.asset !== CASH) wanted[p.asset] = p.rawDelta; });
    } else if (settings.mode === "band") {
      base.forEach(p => { if (p.asset !== CASH && p.breach) wanted[p.asset] = p.rawDelta; });
    } else {
      // Dana baru: beli yang kurang, proporsional terhadap kekurangannya, tanpa menjual.
      const cashRow = base.find(p => p.asset === CASH);
      const budget = Math.max(0, (cashRow?.value ?? 0) - (cashRow?.tgtUsd ?? 0));
      const short = base.filter(p => p.asset !== CASH && p.rawDelta > 0);
      const need = short.reduce((s, p) => s + p.rawDelta, 0);
      const scale = need > 0 ? Math.min(1, budget / need) : 0;
      wanted = Object.fromEntries(short.map(p => [p.asset, p.rawDelta * scale]));
    }

    const lines = base.map(p => {
      if (p.asset === CASH) return { ...p, deltaUsd: 0, deltaQty: 0, hold: "" };
      const want = wanted[p.asset] ?? 0;
      const f = filters[`${p.asset}${CASH}`];
      const minOrder = f?.min_notional || FALLBACK_MIN_ORDER;
      let qty = p.current_price > 0 ? Math.abs(want) / p.current_price : 0;
      if (want < 0) qty = Math.min(qty, p.total);           // tak bisa jual melebihi saldo
      qty = floorStep(qty, f?.step_size ?? 0);
      const usd = qty * p.current_price;
      let hold = "";
      if (want === 0) hold = settings.mode === "band" ? "dalam pita" : "";
      else if (qty <= 0 || (f && qty < f.min_qty) || usd < minOrder) hold = `< min order $${minOrder}`;
      const sign = want >= 0 ? 1 : -1;
      return { ...p, deltaUsd: hold || want === 0 ? 0 : sign * usd, deltaQty: hold || want === 0 ? 0 : sign * qty, hold };
    });

    const fee = lines.reduce((s, l) => s + Math.abs(l.deltaUsd) * FEE_RATE, 0);
    const netCoin = lines.reduce((s, l) => s + (l.asset === CASH ? 0 : l.deltaUsd), 0);
    return lines.map(l => (l.asset === CASH ? { ...l, deltaUsd: -netCoin - fee } : l));
  }, [rows, targets, total, totalNow, extra, filters, settings.mode, settings.anchor, settings.anchorMin, settings.bandAbs, settings.bandRel]);

  const sumTarget = useMemo(() => plan.reduce((s, p) => s + p.tgtPct, 0), [plan]);
  const sumOk = Math.abs(sumTarget - 100) < 0.05;
  const hasTargets = plan.some(p => p.tgtPct > 0);
  const anchorTgt = targets[settings.anchor] ?? 0;
  const anchorViolation = anchorPresent && hasTargets && anchorTgt < settings.anchorMin;
  const anchorNow = plan.find(p => p.asset === settings.anchor)?.curPct ?? 0;

  const totalDrift = useMemo(() => plan.reduce((s, p) => s + Math.abs(p.curPct - p.tgtPct), 0) / 2, [plan]);
  const breaches = plan.filter(p => p.breach);
  const sells = plan.filter(p => p.asset !== CASH && p.deltaUsd < 0);
  const buys = plan.filter(p => p.asset !== CASH && p.deltaUsd > 0);
  const turnover = [...sells, ...buys].reduce((s, p) => s + Math.abs(p.deltaUsd), 0);
  const fees = turnover * FEE_RATE;
  const cashLine = plan.find(p => p.asset === CASH);
  const cashAfter = (cashLine?.value ?? 0) + (cashLine?.deltaUsd ?? 0);
  const [now] = useState(() => Date.now());
  const daysSince = settings.lastDone ? Math.floor((now - settings.lastDone) / 86400000) : null;

  const ready = hasTargets && sumOk && !anchorViolation;

  return (
    <div className="bg-white rounded-2xl border border-neutral-200 overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4 border-b border-neutral-100 bg-neutral-50">
        <div className="min-w-0">
          <h3 className="font-bold text-sm text-neutral-700">⚖️ Kalkulator Target Bobot (Rebalancing)</h3>
          <p className="text-[11px] text-neutral-500 mt-0.5">
            Tentukan porsi ideal tiap koin di dompet Binance Anda — kalkulator menghitung order yang perlu
            dipasang supaya porsinya kembali sesuai rencana. Hanya menghitung, tidak memasang order.
          </p>
          <button type="button" onClick={toggleGuide} className="mt-1 text-[11px] font-semibold text-teal-700 hover:underline">
            {showGuide ? "Tutup penjelasan" : "Apa ini & cara pakainya?"}
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5 shrink-0">
          <button type="button" onClick={applyCurrent} disabled={rows.length === 0}
            className="text-[11px] font-semibold px-2.5 py-1 rounded-lg border border-neutral-200 text-neutral-600 hover:bg-neutral-100 disabled:opacity-40">
            Pakai bobot sekarang
          </button>
          <button type="button" onClick={applyEqual} disabled={rows.length === 0}
            className="text-[11px] font-semibold px-2.5 py-1 rounded-lg border border-teal-200 text-teal-700 bg-teal-50 hover:bg-teal-100 disabled:opacity-40">
            {anchorPresent ? `${settings.anchor} ${settings.anchorMin}% + sisa rata` : "Bobot sama rata"}
          </button>
        </div>
      </div>

      {showGuide && (
        <div className="px-5 py-4 border-b border-neutral-100 bg-teal-50/40 text-xs text-neutral-600 space-y-2">
          <p>
            <span className="font-bold text-neutral-700">Tujuannya:</span> menjaga komposisi aset tetap sesuai rencana Anda.
            Kalau satu koin naik tinggi, porsinya membengkak dan risiko menumpuk di koin itu. Rebalancing mengembalikan
            porsi: jual sebagian yang berlebih, beli yang kurang — sekaligus disiplin &quot;jual saat mahal, beli saat murah&quot;.
          </p>
          <ol className="list-decimal pl-4 space-y-1">
            <li>Isi <span className="font-semibold">Porsi yang diinginkan</span> sampai totalnya 100% (baris USDT = kas), atau pakai tombol preset.</li>
            <li>Pilih <span className="font-semibold">metode</span> di baris pengaturan. Bawaan: <span className="font-semibold">Pita toleransi</span>.</li>
            <li>Ikuti <span className="font-semibold">Rencana order</span>: jual dulu, baru beli. Pasang sendiri di Binance, lalu klik <span className="font-semibold">Sudah saya eksekusi</span>.</li>
          </ol>
          <p className="font-semibold text-neutral-700 pt-1">Tiga metode:</p>
          <ul className="list-disc pl-4 space-y-1">
            <li><span className="font-semibold">Pita toleransi (aturan 5/25)</span> — hanya koin yang menyimpang lebih dari {settings.bandAbs} poin
              {" "}<em>atau</em> {settings.bandRel}% dari targetnya (mana yang lebih kecil) yang ditransaksikan. Penyimpangan kecil dibiarkan supaya
              tidak boros fee. Periksa rutin (mis. tiap bulan) dan eksekusi hanya bila ada yang keluar pita.</li>
            <li><span className="font-semibold">Penuh</span> — semua koin dikembalikan tepat ke target. Paling presisi, paling banyak fee.</li>
            <li><span className="font-semibold">Dana baru (tanpa jual)</span> — kas/setoran baru dipakai membeli koin yang porsinya kurang. Tidak ada penjualan.</li>
          </ul>
          <p>
            <span className="font-semibold text-neutral-700">Aturan {settings.anchor} minimal {settings.anchorMin}%</span> — porsi minimum yang Anda tetapkan,
            karena altcoin biasanya bergerak lebih tajam dari {settings.anchor}. Target di bawah batas ini ditolak, dan porsi {settings.anchor} yang jatuh
            di bawahnya selalu memicu rebalance.
          </p>
          <p className="text-neutral-500">
            Jumlah koin sudah dibulatkan ke kelipatan yang diterima Binance dan dicek terhadap minimum order; fee 0,1% ikut dihitung.
            Porsi target adalah keputusan Anda — kalkulator hanya menghitung cara mencapainya. Pengaturan tersimpan di browser ini saja.
          </p>
        </div>
      )}

      {/* Pengaturan metode */}
      <div className="px-5 py-3 border-b border-neutral-100 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-neutral-400 mr-1">Metode:</span>
          {([["band", "Pita toleransi"], ["full", "Penuh"], ["cash", "Dana baru (tanpa jual)"]] as [Mode, string][]).map(([m, label]) => (
            <button key={m} type="button" onClick={() => setSetting("mode", m)}
              className={`px-2 py-0.5 rounded-md border text-[11px] font-semibold ${settings.mode === m
                ? "border-teal-400 bg-teal-50 text-teal-700" : "border-neutral-200 text-neutral-500 hover:bg-neutral-50"}`}>
              {label}
            </button>
          ))}
        </div>
        {settings.mode === "band" && (
          <label className="flex items-center gap-1 text-neutral-500">
            pita ±
            <input type="number" min={0.5} max={20} step={0.5} value={settings.bandAbs}
              onChange={e => setSetting("bandAbs", Math.max(0.5, Number(e.target.value) || 5))}
              className="w-12 text-right font-mono px-1 py-0.5 rounded border border-neutral-200" />
            poin / ±
            <input type="number" min={5} max={100} step={5} value={settings.bandRel}
              onChange={e => setSetting("bandRel", Math.max(1, Number(e.target.value) || 25))}
              className="w-12 text-right font-mono px-1 py-0.5 rounded border border-neutral-200" />
            % dari target
          </label>
        )}
        {settings.mode === "cash" && (
          <label className="flex items-center gap-1 text-neutral-500">
            setoran baru
            <input type="number" min={0} step={10} value={settings.extraCash}
              onChange={e => setSetting("extraCash", Math.max(0, Number(e.target.value) || 0))}
              className="w-20 text-right font-mono px-1 py-0.5 rounded border border-neutral-200" />
            USDT
          </label>
        )}
        <label className="flex items-center gap-1 text-neutral-500">
          {settings.anchor} minimal
          <input type="number" min={0} max={100} step={1} value={settings.anchorMin}
            onChange={e => setSetting("anchorMin", Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
            className="w-12 text-right font-mono px-1 py-0.5 rounded border border-neutral-200" />
          %
        </label>
      </div>

      {error && <p className="px-5 py-4 text-xs text-neutral-400">Data holding tidak tersedia — kalkulator menunggu Spot Portfolio.</p>}
      {loading && !error && <p className="px-5 py-4 text-xs text-neutral-400">Memuat holding...</p>}

      {!loading && !error && rows.length > 0 && (
        <>
          {hasTargets && (
            <div className="px-5 py-2.5 border-b border-neutral-100 text-xs flex flex-wrap gap-x-5 gap-y-1">
              <span>Penyimpangan dari target: <span className="font-bold tabular-nums">{totalDrift.toFixed(1)}%</span></span>
              {anchorPresent && (
                <span className={anchorNow < settings.anchorMin ? "text-red-500 font-semibold" : "text-neutral-500"}>
                  Porsi {settings.anchor} sekarang {anchorNow.toFixed(1)}%{" "}
                  {anchorNow < settings.anchorMin ? `(di bawah minimum ${settings.anchorMin}%)` : `(≥ ${settings.anchorMin}% ✓)`}
                </span>
              )}
              {settings.mode === "band" && (
                <span className={breaches.length ? "text-amber-600 font-semibold" : "text-green-600 font-semibold"}>
                  {breaches.length ? `${breaches.length} koin keluar pita → perlu rebalance` : "Semua dalam pita → belum perlu rebalance"}
                </span>
              )}
              {daysSince !== null && <span className="text-neutral-400">Rebalance terakhir {daysSince === 0 ? "hari ini" : `${daysSince} hari lalu`}</span>}
            </div>
          )}

          <div className="hidden md:grid grid-cols-[1.3fr_0.9fr_1fr_1fr_1fr_1.5fr] gap-x-4 px-5 py-2 text-[10px] font-bold text-neutral-400 uppercase tracking-wider border-b border-neutral-100 bg-neutral-50/50">
            <span>Aset</span><span className="text-right">Porsi sekarang</span><span className="text-right">Porsi yang diinginkan</span>
            <span className="text-right">Nilai yang diinginkan</span><span className="text-right">Kurang / lebih</span><span className="text-right">Yang perlu dilakukan</span>
          </div>
          <div className="divide-y divide-neutral-100">
            {plan.map(p => {
              const isCash = p.asset === CASH;
              const isAnchor = p.asset === settings.anchor;
              const act = !isCash && p.deltaUsd !== 0;
              const buy = p.deltaUsd > 0;
              const cls = buy ? "text-green-600" : "text-red-500";
              const gap = p.tgtUsd - p.value;
              return (
                <div key={p.asset} className="px-5 py-3 grid grid-cols-2 md:grid-cols-[1.3fr_0.9fr_1fr_1fr_1fr_1.5fr] gap-x-4 gap-y-1.5 items-center">
                  <div>
                    <p className="font-bold text-sm">
                      {p.asset}
                      {isAnchor && <span className="ml-1.5 text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">min {settings.anchorMin}%</span>}
                    </p>
                    <p className="text-[10px] text-neutral-400">${p.usdt_value.toFixed(2)} · {isCash ? "kas" : `@ $${fmtPrice(p.current_price)}`}</p>
                  </div>
                  <div className={`text-right text-sm font-mono ${p.breach ? "text-amber-600 font-bold" : "text-neutral-700"}`}>
                    {p.curPct.toFixed(1)}%
                  </div>
                  <div className="flex justify-end">
                    <div className="relative">
                      <input type="number" min={0} max={100} step={0.5} inputMode="decimal"
                        value={targets[p.asset] ?? ""} placeholder="0"
                        onChange={e => setTarget(p.asset, e.target.value)}
                        className={`w-20 text-right text-sm font-mono pr-6 pl-2 py-1 rounded-lg border focus:outline-none ${
                          isAnchor && anchorViolation ? "border-red-400" : "border-neutral-200 focus:border-teal-400"}`} />
                      <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-neutral-400">%</span>
                    </div>
                  </div>
                  <div className="text-right text-sm font-mono text-neutral-700">${p.tgtUsd.toFixed(2)}</div>
                  <div className="text-right text-sm font-mono text-neutral-600">
                    {gap >= 0 ? "kurang " : "lebih "}${Math.abs(gap).toFixed(2)}
                  </div>
                  <div className="text-right col-span-2 md:col-span-1">
                    {isCash ? (
                      <span className="text-xs text-neutral-500">kas setelahnya ≈ ${cashAfter.toFixed(2)}</span>
                    ) : act ? (
                      <>
                        <span className={`text-xs font-black ${cls}`}>{buy ? "BELI" : "JUAL"}</span>
                        <p className="text-[10px] font-mono text-neutral-500">
                          {fmtQty(p.deltaQty)} {p.asset} (~${Math.abs(p.deltaUsd).toFixed(2)})
                        </p>
                      </>
                    ) : (
                      <span className="text-xs font-bold text-neutral-400">Tahan{p.hold ? ` · ${p.hold}` : ""}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {hasTargets && (!sumOk || anchorViolation) && (
            <div className="px-5 py-3 border-t border-neutral-100 text-xs text-amber-700 bg-amber-50 space-y-0.5">
              {!sumOk && (
                <p>Total porsi yang diinginkan {sumTarget.toFixed(1)}% — harus tepat 100%{" "}
                  ({sumTarget > 100 ? `kurangi ${(sumTarget - 100).toFixed(1)}%` : `tambah ${(100 - sumTarget).toFixed(1)}%`}).</p>
              )}
              {anchorViolation && <p>Target {settings.anchor} {anchorTgt}% di bawah aturan minimum {settings.anchorMin}% — naikkan dulu.</p>}
            </div>
          )}

          {ready && (
            <div className="px-5 py-3 border-t border-neutral-100 text-xs text-neutral-600 space-y-1.5">
              {sells.length + buys.length === 0 ? (
                <p><span className="font-bold text-green-600">Tidak ada order yang perlu dipasang.</span>{" "}
                  {settings.mode === "band" ? "Semua koin masih dalam pita toleransi." : "Semua selisih di bawah minimum order."}</p>
              ) : (
                <>
                  <p className="font-bold text-neutral-700">Rencana order (urut — jual dulu, baru beli):</p>
                  <ol className="list-decimal pl-4 space-y-0.5 font-mono">
                    {[...sells, ...buys].map(p => (
                      <li key={p.asset}>
                        <span className={p.deltaUsd > 0 ? "text-green-600 font-semibold" : "text-red-500 font-semibold"}>
                          {p.deltaUsd > 0 ? "BELI" : "JUAL"} {fmtQty(p.deltaQty)} {p.asset}
                        </span>{" "}≈ ${Math.abs(p.deltaUsd).toFixed(2)}
                      </li>
                    ))}
                  </ol>
                  <p className="text-neutral-500">
                    Total diperdagangkan ${turnover.toFixed(2)} ({total > 0 ? ((turnover / total) * 100).toFixed(1) : "0"}% aset) ·
                    perkiraan fee ${fees.toFixed(2)} · kas setelahnya ≈ ${cashAfter.toFixed(2)}
                  </p>
                  {cashAfter < -0.01 && (
                    <p className="text-red-500 font-semibold">Kas tidak cukup untuk semua pembelian — kurangi target koin atau tambah setoran.</p>
                  )}
                  <button type="button" onClick={() => setSetting("lastDone", Date.now())}
                    className="mt-1 text-[11px] font-semibold px-2.5 py-1 rounded-lg border border-teal-200 text-teal-700 bg-teal-50 hover:bg-teal-100">
                    Sudah saya eksekusi
                  </button>
                </>
              )}
            </div>
          )}

          <div className="px-5 py-3 bg-neutral-50 border-t border-neutral-200 flex flex-wrap items-center justify-between gap-3 text-xs">
            <div>
              <span className="text-neutral-400">Total porsi yang diinginkan: </span>
              <span className={`font-black tabular-nums ${sumOk ? "text-green-600" : "text-amber-600"}`}>{sumTarget.toFixed(1)}%</span>
              {!hasTargets && <span className="ml-2 text-neutral-400">isi porsi atau pilih preset di atas</span>}
            </div>
            <div className="text-neutral-500">
              Total aset <span className="font-bold text-neutral-700">${totalNow.toFixed(2)}</span>
              {extra > 0 && <> + setoran <span className="font-bold text-neutral-700">${extra.toFixed(2)}</span></>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
