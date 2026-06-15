"use client";
import { fmtPrice } from "@/lib/format";
import { EmptyState, LoadingPage } from "@/components/ui/feedback";

export interface SpotAsset {
  asset: string; total: number; usdt_value: number;
  current_price: number; avg_buy_price: number | null;
  pnl_percent: number | null; pnl_usdt: number | null;
}

function AssetAvatar({ asset }: { asset: string }) {
  return (
    <div className="w-9 h-9 rounded-full bg-teal-50 border border-teal-200 flex items-center justify-center shrink-0">
      <span className="text-[9px] font-black text-teal-700">{asset.slice(0, 3)}</span>
    </div>
  );
}

function fmtAmount(n: number): string {
  if (n < 0.001) return n.toFixed(6);
  if (n < 1)     return n.toFixed(4);
  if (n < 1000)  return n.toFixed(2);
  return Math.round(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function SpotPortfolioPanel({ assets, loading, error }: {
  assets: SpotAsset[]; loading: boolean; error: string | null;
}) {
  const totalValue   = assets.reduce((s, a) => s + a.usdt_value, 0);
  const totalPnlUSD  = assets.reduce((s, a) => s + (a.pnl_usdt ?? 0), 0);
  const totalCost    = assets.reduce((s, a) => {
    if (a.avg_buy_price == null || a.avg_buy_price === 0) return s;
    return s + a.avg_buy_price * a.total;
  }, 0);

  return (
    <div className="bg-white rounded-2xl border border-neutral-200 overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between px-5 py-4 border-b border-neutral-100 bg-neutral-50">
        <div>
          <h3 className="font-bold text-sm text-neutral-700">💼 Spot Portfolio — Real Holdings</h3>
          <p className="text-[10px] text-neutral-400 mt-0.5">Saldo nyata Binance · Harga masuk (FIFO) · Unrealized PnL</p>
        </div>
        <div className="text-right">
          {loading ? (
            <div className="flex items-center gap-1.5 text-xs text-neutral-400">
              <span className="w-3 h-3 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />Memuat...
            </div>
          ) : error ? (
            <span className="text-xs text-red-500">⚠ Error</span>
          ) : assets.length > 0 ? (
            <>
              <p className="text-xl font-black text-neutral-900 tabular-nums">${totalValue.toFixed(2)}</p>
              <p className={`text-xs font-bold ${totalPnlUSD >= 0 ? "text-green-600" : "text-red-500"}`}>
                {totalPnlUSD >= 0 ? "+" : ""}${totalPnlUSD.toFixed(2)} unrealized
                {totalCost > 0 && <span className="text-neutral-400 font-normal ml-1">(modal ${totalCost.toFixed(0)})</span>}
              </p>
            </>
          ) : (
            <span className="text-xs text-neutral-400">Tidak ada holding</span>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="px-5 py-6 text-center">
          <div className="inline-flex flex-col items-center gap-3 max-w-sm">
            <span className="text-4xl">🔑</span>
            <div>
              <p className="font-bold text-neutral-700 mb-1">Tidak bisa memuat Spot Holdings</p>
              <p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2 font-mono mb-3">{error}</p>
              <div className="text-left text-xs text-neutral-600 space-y-1.5 bg-amber-50 border border-amber-200 rounded-xl p-3">
                <p className="font-bold text-amber-700 mb-2">Kemungkinan penyebab:</p>
                <p>1️⃣ <strong>API Key belum diset</strong> — tambahkan <code className="bg-white px-1 rounded">BINANCE_API_KEY</code> di <code className="bg-white px-1 rounded">backend/.env</code></p>
                <p>2️⃣ <strong>Permission tidak cukup</strong> — pastikan &quot;Enable Reading&quot; + &quot;Enable Spot&quot; aktif</p>
                <p>3️⃣ <strong>API Key hanya untuk Futures</strong> — buat API Key baru dengan akses Spot</p>
              </div>
              <a href="/api/v1/market/spot-debug" target="_blank" rel="noreferrer"
                className="inline-block mt-2 text-xs text-teal-600 hover:text-teal-500 underline font-semibold">
                🔍 Buka Spot Debug →
              </a>
            </div>
          </div>
        </div>
      )}

      {loading && !error && <LoadingPage message="Memuat portfolio Binance spot..." />}

      {!loading && !error && assets.length === 0 && (
        <EmptyState icon="📭" title="Tidak ada spot holdings terdeteksi" subtitle="Semua aset < $0.01 USDT atau akun spot kosong" />
      )}

      {!loading && !error && assets.length > 0 && (
        <>
          {/* Column headers */}
          <div className="hidden md:grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr] gap-x-4 px-5 py-2 text-[10px] font-bold text-neutral-400 uppercase tracking-wider border-b border-neutral-100 bg-neutral-50/50">
            <span>Aset</span><span className="text-right">Harga Masuk</span><span className="text-right">Harga Sekarang</span>
            <span className="text-right">Jumlah</span><span className="text-right">Nilai USDT</span><span className="text-right">PnL</span>
          </div>
          <div className="divide-y divide-neutral-100">
            {assets.map(a => {
              const pct      = totalValue > 0 ? (a.usdt_value / totalValue) * 100 : 0;
              const hasPnl   = a.pnl_usdt != null && a.avg_buy_price != null && a.avg_buy_price > 0;
              const profit   = (a.pnl_usdt ?? 0) >= 0;
              const invested = a.avg_buy_price != null ? a.avg_buy_price * a.total : null;
              return (
                <div key={a.asset} className="px-5 py-3 hover:bg-neutral-50 transition-colors">
                  {/* Mobile */}
                  <div className="md:hidden flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <AssetAvatar asset={a.asset} />
                      <div>
                        <span className="font-bold text-sm">{a.asset}</span>
                        <p className="text-[10px] text-neutral-400">{pct.toFixed(1)}% portfolio</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="font-bold text-sm tabular-nums">${a.usdt_value.toFixed(2)}</p>
                      {hasPnl && (
                        <p className={`text-xs font-bold ${profit ? "text-green-600" : "text-red-500"}`}>
                          {profit ? "+" : ""}{a.pnl_usdt!.toFixed(2)} USDT
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Desktop */}
                  <div className="hidden md:grid grid-cols-[2fr_1fr_1fr_1fr_1fr_1fr] gap-x-4 items-center">
                    <div className="flex items-center gap-3 min-w-0">
                      <AssetAvatar asset={a.asset} />
                      <div className="min-w-0">
                        <p className="font-bold text-sm">{a.asset}</p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <div className="flex-1 bg-neutral-100 rounded-full h-1 w-20">
                            <div className="bg-teal-400 h-full rounded-full" style={{ width: `${Math.min(pct, 100)}%` }} />
                          </div>
                          <span className="text-[10px] text-neutral-400">{pct.toFixed(1)}%</span>
                        </div>
                      </div>
                    </div>
                    <div className="text-right">
                      {a.avg_buy_price != null && a.avg_buy_price > 0 ? (
                        <>
                          <p className="text-sm font-mono font-bold text-neutral-800">${fmtPrice(a.avg_buy_price)}</p>
                          {invested != null && <p className="text-[10px] text-neutral-400">≈ ${invested.toFixed(2)}</p>}
                        </>
                      ) : <span className="text-neutral-300 text-xs">—</span>}
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-mono font-bold text-neutral-800">${fmtPrice(a.current_price)}</p>
                      {a.asset !== "USDT" && a.avg_buy_price != null && a.avg_buy_price > 0 && (
                        <p className={`text-[10px] font-semibold ${a.current_price >= a.avg_buy_price ? "text-green-500" : "text-red-400"}`}>
                          {a.current_price >= a.avg_buy_price ? "▲" : "▼"} {Math.abs(((a.current_price - a.avg_buy_price) / a.avg_buy_price) * 100).toFixed(1)}% vs masuk
                        </p>
                      )}
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-mono font-bold text-neutral-700">{fmtAmount(a.total)}</p>
                      <p className="text-[10px] text-neutral-400">{a.asset}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-bold tabular-nums text-neutral-800">
                        {a.usdt_value < 1000 ? `$${a.usdt_value.toFixed(2)}` : `$${(a.usdt_value / 1000).toFixed(2)}K`}
                      </p>
                    </div>
                    <div className="text-right">
                      {hasPnl ? (
                        <>
                          <p className={`text-sm font-black tabular-nums ${profit ? "text-green-600" : "text-red-500"}`}>
                            {profit ? "+" : ""}${a.pnl_usdt!.toFixed(2)}
                          </p>
                          <p className={`text-[10px] font-bold ${profit ? "text-green-500" : "text-red-400"}`}>
                            {profit ? "+" : ""}{a.pnl_percent!.toFixed(2)}%
                          </p>
                        </>
                      ) : <span className="text-neutral-300 text-xs">—</span>}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Footer summary */}
          <div className="px-5 py-3 bg-neutral-50 border-t border-neutral-200">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Total Nilai",   value: `$${totalValue.toFixed(2)}`,  cls: "text-neutral-800" },
                { label: "Total Modal",   value: totalCost > 0 ? `$${totalCost.toFixed(2)}` : "—", cls: "text-neutral-700" },
                { label: "Unrealized PnL", value: `${totalPnlUSD >= 0 ? "+" : ""}$${totalPnlUSD.toFixed(2)}`, cls: totalPnlUSD >= 0 ? "text-green-600" : "text-red-500" },
                { label: "ROI", value: totalCost > 0 ? `${totalPnlUSD >= 0 ? "+" : ""}${((totalPnlUSD / totalCost) * 100).toFixed(1)}%` : "—", cls: totalPnlUSD >= 0 ? "text-green-600" : "text-red-500" },
              ].map(x => (
                <div key={x.label}>
                  <p className="text-[10px] text-neutral-400 uppercase tracking-wide font-semibold mb-0.5">{x.label}</p>
                  <p className={`font-black text-base tabular-nums ${x.cls}`}>{x.value}</p>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
