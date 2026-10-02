"use client";
import { useCallback, useMemo, useState } from "react";
import { fmtPrice } from "@/lib/format";
import type { SpotAsset } from "./SpotPortfolioPanel";

const STORAGE_KEY = "rebalance-targets-v1";
const GUIDE_KEY = "rebalance-guide-v1";
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

  // Penjelasan terbuka untuk pengguna baru; sekali ditutup, pilihan itu diingat.
  const [showGuide, setShowGuideRaw] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    try { return localStorage.getItem(GUIDE_KEY) !== "closed"; } catch { return true; }
  });
  const setShowGuide = useCallback((next: (v: boolean) => boolean) => {
    setShowGuideRaw(prev => {
      const v = next(prev);
      try { localStorage.setItem(GUIDE_KEY, v ? "open" : "closed"); } catch { /* storage blocked */ }
      return v;
    });
  }, []);

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

  const exampleRow = useMemo(() => plan.find(p => p.asset !== CASH) ?? null, [plan]);

  // Ringkasan dalam kalimat: hanya aksi di atas minimum order.
  const actions = useMemo(() => plan
    .filter(p => p.asset !== CASH && Math.abs(p.deltaUsd) >= MIN_ORDER_USDT)
    .map(p => ({ asset: p.asset, buy: p.deltaUsd > 0, usd: Math.abs(p.deltaUsd), qty: Math.abs(p.deltaQty) })),
  [plan]);

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
          <h3 className="font-bold text-sm text-neutral-700">⚖️ Kalkulator Target Bobot (Rebalancing)</h3>
          <p className="text-[11px] text-neutral-500 mt-0.5">
            Tentukan porsi ideal tiap koin di dompet Binance Anda — kalkulator menghitung berapa yang perlu
            dijual atau dibeli supaya porsinya pas. Hanya menghitung, tidak memasang order.
          </p>
          <button type="button" onClick={() => setShowGuide(v => !v)}
            className="mt-1 text-[11px] font-semibold text-teal-700 hover:underline">
            {showGuide ? "Tutup penjelasan" : "Apa ini & cara pakainya?"}
          </button>
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

      {showGuide && (
        <div className="px-5 py-4 border-b border-neutral-100 bg-teal-50/40 text-xs text-neutral-600 space-y-2">
          <p>
            <span className="font-bold text-neutral-700">Tujuannya:</span> menjaga komposisi aset tetap sesuai rencana.
            Kalau satu koin naik tinggi, porsinya membengkak dan risiko Anda menumpuk di koin itu. Rebalancing
            mengembalikan porsi ke rencana: jual sebagian yang porsinya berlebih, beli yang porsinya kurang.
          </p>
          <ol className="list-decimal pl-4 space-y-1">
            <li>Klik <span className="font-semibold">Pakai bobot sekarang</span> untuk mulai dari komposisi saat ini, atau <span className="font-semibold">Bobot sama rata</span>.</li>
            <li>Ubah kolom <span className="font-semibold">Porsi yang diinginkan</span> sampai totalnya <span className="font-semibold">100%</span>. Baris USDT = porsi yang ingin disimpan sebagai kas.</li>
            <li>Baca kolom <span className="font-semibold">Yang perlu dilakukan</span>: <span className="text-green-600 font-semibold">BELI</span> / <span className="text-red-500 font-semibold">JUAL</span> beserta jumlah koinnya, lalu pasang ordernya sendiri di Binance.</li>
          </ol>
          {exampleRow && total > 0 && (
            <p className="text-neutral-500">
              <span className="font-semibold text-neutral-700">Contoh dari dompet Anda:</span> total aset ${total.toFixed(2)};{" "}
              {exampleRow.asset} sekarang ${exampleRow.usdt_value.toFixed(2)} ({exampleRow.curPct.toFixed(1)}%).
              Kalau porsi yang diinginkan 50%, nilai idealnya ${(total * 0.5).toFixed(2)} → perlu{" "}
              {total * 0.5 - exampleRow.usdt_value >= 0 ? "beli" : "jual"} {exampleRow.asset} senilai ${Math.abs(total * 0.5 - exampleRow.usdt_value).toFixed(2)}.
            </p>
          )}
          <p className="text-neutral-500">
            <span className="font-semibold">Tahan</span> = selisihnya di bawah ${MIN_ORDER_USDT} (minimum order Binance), jadi tidak perlu dieksekusi.
            Porsi yang Anda isi hanya tersimpan di browser ini.
          </p>
        </div>
      )}

      {error && <p className="px-5 py-4 text-xs text-neutral-400">Data holding tidak tersedia — kalkulator menunggu Spot Portfolio.</p>}
      {loading && !error && <p className="px-5 py-4 text-xs text-neutral-400">Memuat holding...</p>}

      {!loading && !error && rows.length > 0 && (
        <>
          <div className="hidden md:grid grid-cols-[1.4fr_1fr_1fr_1fr_1.2fr_1.4fr] gap-x-4 px-5 py-2 text-[10px] font-bold text-neutral-400 uppercase tracking-wider border-b border-neutral-100 bg-neutral-50/50">
            <span>Aset</span><span className="text-right">Porsi sekarang</span><span className="text-right">Porsi yang diinginkan</span>
            <span className="text-right">Nilai yang diinginkan</span><span className="text-right">Kurang / lebih</span><span className="text-right">Yang perlu dilakukan</span>
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
                      <p className="text-[10px] font-mono text-neutral-500">
                        {buy ? "beli" : "jual"} {fmtQty(p.deltaQty)} {p.asset}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {hasTargets && sumOk && (
            <div className="px-5 py-3 border-t border-neutral-100 text-xs text-neutral-600">
              {actions.length === 0 ? (
                <span><span className="font-bold text-green-600">Sudah seimbang.</span> Semua selisih di bawah ${MIN_ORDER_USDT} — tidak ada yang perlu dijual/dibeli.</span>
              ) : (
                <span>
                  <span className="font-bold text-neutral-700">Untuk mencapai target: </span>
                  {actions.map((a, i) => (
                    <span key={a.asset}>
                      {i > 0 && ", "}
                      <span className={a.buy ? "text-green-600 font-semibold" : "text-red-500 font-semibold"}>
                        {a.buy ? "beli" : "jual"} {fmtQty(a.qty)} {a.asset}
                      </span> (~${a.usd.toFixed(2)})
                    </span>
                  ))}
                  . Jual dulu, baru beli, supaya kasnya cukup.
                </span>
              )}
            </div>
          )}

          <div className="px-5 py-3 bg-neutral-50 border-t border-neutral-200 flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs">
              <span className="text-neutral-400">Total porsi yang diinginkan: </span>
              <span className={`font-black tabular-nums ${sumOk ? "text-green-600" : "text-amber-600"}`}>{sumTarget.toFixed(1)}%</span>
              {!sumOk && hasTargets && (
                <span className="ml-2 text-amber-600">
                  {sumTarget > 100 ? `lebih ${(sumTarget - 100).toFixed(1)}%` : `kurang ${(100 - sumTarget).toFixed(1)}% (sisanya dianggap tidak dialokasikan)`}
                </span>
              )}
              {!hasTargets && <span className="ml-2 text-neutral-400">isi target atau pilih preset di atas</span>}
            </div>
            <div className="text-xs text-neutral-500">
              Total aset <span className="font-bold text-neutral-700">${total.toFixed(2)}</span>
              {hasTargets && (
                <> · total yang diperdagangkan <span className="font-bold text-neutral-700">${turnover.toFixed(2)}</span>
                  <span className="text-neutral-400"> ({total > 0 ? ((turnover / total) * 100).toFixed(1) : "0"}%, belum termasuk fee)</span></>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
