"use client";
import { useCallback, useMemo, useState } from "react";
import { fmtPrice } from "@/lib/format";
import type { SpotAsset } from "./SpotPortfolioPanel";

const STORAGE_KEY = "rebalance-targets-v1";
const CASH = "USDT";
/** Aset di bawah nilai ini dianggap debu — tak masuk kalkulasi bobot. */
const DUST_USDT = 1;
/** Selisih di bawah nilai ini tidak layak dieksekusi (minimum order Binance ≈ $5). */
const MIN_ORDER_USDT = 5;

type Targets = Record<string, number>;

function loadTargets(): Targets {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Targets) : {};
  } catch { return {}; }
}
function saveTargets(t: Targets) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(t)); } catch { /* private mode / storage blocked */ }
}

function fmtQty(n: number): string {
  const v = Math.abs(n);
  if (v < 0.001) return v.toFixed(6);
  if (v < 1)     return v.toFixed(4);
  if (v < 1000)  return v.toFixed(3);
  return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

/**
 * Kalkulator "target bobot → berapa yang dijual/dibeli".
 * Murni hitung di sisi klien: tidak ada tombol eksekusi — order tetap dilakukan sendiri di Binance.
 */
export function RebalanceCalculator({ assets, loading, error }: {
  assets: SpotAsset[]; loading: boolean; error: string | null;
}) {
  // Komponen ini di-render client-only (dashboard "use client"), jadi aman baca localStorage di initializer.
  const [targets, setTargetsRaw] = useState<Targets>(() => (typeof window === "undefined" ? {} : loadTargets()));
  const setTargets = useCallback((next: Targets | ((prev: Targets) => Targets)) => {
    setTargetsRaw(prev => {
      const v = typeof next === "function" ? next(prev) : next;
      saveTargets(v);
      return v;
    });
  }, []);

  // Baris kalkulasi: aset non-debu + selalu satu baris kas USDT (walau saldonya 0).
  const rows = useMemo(() => {
    const live = assets.filter(a => a.asset !== CASH && a.usdt_value >= DUST_USDT);
    const cash = assets.find(a => a.asset === CASH);
    const cashRow: SpotAsset = cash ?? {
      asset: CASH, total: 0, usdt_value: 0, current_price: 1, avg_buy_price: 1, pnl_percent: null, pnl_usdt: null,
    };
    return [...live.sort((a, b) => b.usdt_value - a.usdt_value), cashRow];
  }, [assets]);

  const total = useMemo(() => rows.reduce((s, a) => s + a.usdt_value, 0), [rows]);

  const setTarget = useCallback((asset: string, raw: string) => {
    const n = Number(raw);
    setTargets(prev => ({ ...prev, [asset]: Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0 }));
  }, [setTargets]);

  const applyEqual = useCallback(() => {
    const coins = rows.filter(r => r.asset !== CASH);
    const each = coins.length ? Math.floor((100 / coins.length) * 10) / 10 : 0;
    const t: Targets = {};
    coins.forEach(c => { t[c.asset] = each; });
    t[CASH] = Math.round((100 - each * coins.length) * 10) / 10;
    setTargets(t);
  }, [rows, setTargets]);

  const applyCurrent = useCallback(() => {
    const t: Targets = {};
    rows.forEach(r => { t[r.asset] = total > 0 ? Math.round((r.usdt_value / total) * 1000) / 10 : 0; });
    setTargets(t);
  }, [rows, total, setTargets]);

  const plan = useMemo(() => rows.map(r => {
    const curPct = total > 0 ? (r.usdt_value / total) * 100 : 0;
    const tgtPct = targets[r.asset] ?? 0;
    const tgtUsd = (tgtPct / 100) * total;
    const deltaUsd = tgtUsd - r.usdt_value;
    const deltaQty = r.current_price > 0 ? deltaUsd / r.current_price : 0;
    return { ...r, curPct, tgtPct, tgtUsd, deltaUsd, deltaQty };
  }), [rows, targets, total]);

  const sumTarget = useMemo(() => plan.reduce((s, p) => s + p.tgtPct, 0), [plan]);
  const sumOk = Math.abs(sumTarget - 100) < 0.05;
  const hasTargets = plan.some(p => p.tgtPct > 0);
  const turnover = useMemo(
    () => plan.filter(p => p.asset !== CASH).reduce((s, p) => s + Math.abs(p.deltaUsd), 0),
    [plan],
  );

  return (
    <div className="bg-white rounded-2xl border border-neutral-200 overflow-hidden">
      <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-neutral-100 bg-neutral-50">
        <div>
          <h3 className="font-bold text-sm text-neutral-700">⚖️ Kalkulator Target Bobot</h3>
          <p className="text-[10px] text-neutral-400 mt-0.5">
            Isi bobot target per aset → berapa USDT &amp; koin yang perlu dijual/dibeli. Hanya hitung — eksekusi tetap di Binance.
          </p>
        </div>
        <div className="flex gap-1.5 shrink-0">
          <button type="button" onClick={applyCurrent} disabled={rows.length === 0}
            className="text-[11px] font-semibold px-2.5 py-1 rounded-lg border border-neutral-200 text-neutral-600 hover:bg-neutral-100 disabled:opacity-40">
            Pakai bobot sekarang
          </button>
          <button type="button" onClick={applyEqual} disabled={rows.length === 0}
            className="text-[11px] font-semibold px-2.5 py-1 rounded-lg border border-teal-200 text-teal-700 bg-teal-50 hover:bg-teal-100 disabled:opacity-40">
            Bobot sama rata
          </button>
        </div>
      </div>

      {error && <p className="px-5 py-4 text-xs text-neutral-400">Data holding tidak tersedia — kalkulator menunggu Spot Portfolio.</p>}
      {loading && !error && <p className="px-5 py-4 text-xs text-neutral-400">Memuat holding...</p>}

      {!loading && !error && rows.length > 0 && (
        <>
          <div className="hidden md:grid grid-cols-[1.4fr_1fr_1fr_1fr_1.2fr_1.4fr] gap-x-4 px-5 py-2 text-[10px] font-bold text-neutral-400 uppercase tracking-wider border-b border-neutral-100 bg-neutral-50/50">
            <span>Aset</span><span className="text-right">Sekarang</span><span className="text-right">Target %</span>
            <span className="text-right">Target USDT</span><span className="text-right">Selisih USDT</span><span className="text-right">Aksi</span>
          </div>
          <div className="divide-y divide-neutral-100">
            {plan.map(p => {
              const isCash = p.asset === CASH;
              const skip = Math.abs(p.deltaUsd) < MIN_ORDER_USDT;
              const buy = p.deltaUsd > 0;
              const actionCls = skip ? "text-neutral-400" : buy ? "text-green-600" : "text-red-500";
              const actionLabel = skip ? "Tahan" : isCash ? (buy ? "Sisa kas naik" : "Kas dipakai") : buy ? "BELI" : "JUAL";
              return (
                <div key={p.asset} className="px-5 py-3 grid grid-cols-2 md:grid-cols-[1.4fr_1fr_1fr_1fr_1.2fr_1.4fr] gap-x-4 gap-y-1.5 items-center">
                  <div>
                    <p className="font-bold text-sm">{p.asset}</p>
                    <p className="text-[10px] text-neutral-400">${p.usdt_value.toFixed(2)} · {isCash ? "kas" : `@ $${fmtPrice(p.current_price)}`}</p>
                  </div>
                  <div className="text-right text-sm font-mono text-neutral-700">{p.curPct.toFixed(1)}%</div>
                  <div className="flex justify-end">
                    <div className="relative">
                      <input
                        type="number" min={0} max={100} step={0.5} inputMode="decimal"
                        value={targets[p.asset] ?? ""}
                        placeholder="0"
                        onChange={e => setTarget(p.asset, e.target.value)}
                        className="w-20 text-right text-sm font-mono pr-6 pl-2 py-1 rounded-lg border border-neutral-200 focus:border-teal-400 focus:outline-none"
                      />
                      <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-neutral-400">%</span>
                    </div>
                  </div>
                  <div className="text-right text-sm font-mono text-neutral-700">${p.tgtUsd.toFixed(2)}</div>
                  <div className={`text-right text-sm font-mono font-bold ${actionCls}`}>
                    {p.deltaUsd >= 0 ? "+" : "−"}${Math.abs(p.deltaUsd).toFixed(2)}
                  </div>
                  <div className="text-right col-span-2 md:col-span-1">
                    <span className={`text-xs font-black ${actionCls}`}>{actionLabel}</span>
                    {!skip && !isCash && (
                      <p className="text-[10px] font-mono text-neutral-500">{fmtQty(p.deltaQty)} {p.asset}</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="px-5 py-3 bg-neutral-50 border-t border-neutral-200 flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs">
              <span className="text-neutral-400">Jumlah target: </span>
              <span className={`font-black tabular-nums ${sumOk ? "text-green-600" : "text-amber-600"}`}>{sumTarget.toFixed(1)}%</span>
              {!sumOk && hasTargets && (
                <span className="ml-2 text-amber-600">
                  {sumTarget > 100 ? `lebih ${(sumTarget - 100).toFixed(1)}%` : `kurang ${(100 - sumTarget).toFixed(1)}% (sisanya dianggap tidak dialokasikan)`}
                </span>
              )}
              {!hasTargets && <span className="ml-2 text-neutral-400">isi target atau pilih preset di atas</span>}
            </div>
            <div className="text-xs text-neutral-500">
              Basis <span className="font-bold text-neutral-700">${total.toFixed(2)}</span>
              {hasTargets && (
                <> · perputaran <span className="font-bold text-neutral-700">${turnover.toFixed(2)}</span>
                  <span className="text-neutral-400"> ({total > 0 ? ((turnover / total) * 100).toFixed(1) : "0"}%, belum termasuk fee)</span></>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
