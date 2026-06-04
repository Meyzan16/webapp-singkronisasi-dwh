"use client";
import { useState, useMemo } from "react";
import { fmtPrice } from "@/lib/format";
import { Pagination } from "@/components/ui/pagination";
import type { PaperTrade, TradeStatus } from "@/types/history";

// ── Constants ──────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20;

const STYLE_META: Record<string, { icon: string; label: string; badge: string }> = {
  scalping:   { icon: "⚡", label: "Scalping",  badge: "bg-yellow-100 text-yellow-700 border-yellow-200" },
  daytrading: { icon: "📅", label: "Day Trade", badge: "bg-blue-100 text-blue-700 border-blue-200"       },
  swing:      { icon: "🌊", label: "Swing",     badge: "bg-teal-100 text-teal-700 border-teal-200"       },
  position:   { icon: "🏔", label: "Position",  badge: "bg-purple-100 text-purple-700 border-purple-200" },
};

const STATUS_CONFIG: Record<TradeStatus, { label: string; color: string; bg: string }> = {
  open: { label: "⏳ Open", color: "text-neutral-600",  bg: "bg-neutral-100"  },
  tp:   { label: "✅ TP",   color: "text-green-700",    bg: "bg-green-100"    },
  sl:   { label: "🛑 SL",   color: "text-red-700",      bg: "bg-red-100"      },
};

const ENTRY_TYPE_META: Record<string, { label: string; badge: string; tip: string }> = {
  at_zone:      { label: "Market",  badge: "bg-green-100 text-green-700 border-green-200",  tip: "Harga sudah di area entry — dapat langsung dibeli/jual"    },
  wait_pullback:{ label: "Limit ↓", badge: "bg-amber-100 text-amber-700 border-amber-200",  tip: "Tunggu harga turun ke support — pasang Limit Buy"          },
  wait_rally:   { label: "Limit ↑", badge: "bg-orange-100 text-orange-700 border-orange-200", tip: "Tunggu harga naik ke resistance — pasang Limit Sell"    },
  market:       { label: "Market",  badge: "bg-green-100 text-green-700 border-green-200",  tip: "Entry di harga pasar"                                      },
};

type FilterTab = "ALL" | "open" | "tp" | "sl";

interface TradeTableProps {
  trades: PaperTrade[];
  loading: boolean;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function TradeTable({ trades, loading }: TradeTableProps) {
  const [tab, setTab]       = useState<FilterTab>("ALL");
  const [style, setStyle]   = useState("ALL");
  const [search, setSearch] = useState("");
  const [page, setPage]     = useState(1);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return trades.filter(t => {
      const matchTab    = tab === "ALL" || t.status === tab;
      const matchStyle  = style === "ALL" || t.style === style;
      const matchSearch = !q || t.symbol.toLowerCase().includes(q);
      return matchTab && matchStyle && matchSearch;
    });
  }, [trades, tab, style, search]);

  // Reset page when filters change
  useMemo(() => { setPage(1); }, [filtered.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated  = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const startIndex = (page - 1) * PAGE_SIZE;

  const counts = {
    ALL:  trades.length,
    open: trades.filter(t => t.status === "open").length,
    tp:   trades.filter(t => t.status === "tp").length,
    sl:   trades.filter(t => t.status === "sl").length,
  };

  return (
    <div className="space-y-4">

      {/* ── Source info banner ──────────────────────────────────────────────── */}
      <div className="bg-neutral-50 border border-neutral-200 rounded-xl p-4 text-xs">
        <div className="flex items-start gap-3">
          <span className="text-lg mt-0.5">🤖</span>
          <div>
            <p className="font-bold text-neutral-800 mb-1">
              Sumber data: Early Breakout Scanner (TA Engine)
            </p>
            <p className="text-neutral-500 leading-relaxed mb-2">
              Setiap hasil scan otomatis dicatat sebagai paper trade. Scanner menggunakan:{" "}
              <span className="font-semibold text-neutral-700">BB Squeeze · Volume Accumulation · RSI · EMA · Pressure Shift</span>
            </p>
            <div className="flex flex-wrap gap-2 mt-2">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-100 text-green-700 border border-green-200 font-semibold">
                ✅ Market — Harga sudah di area S/R, entry langsung
              </span>
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-100 text-amber-700 border border-amber-200 font-semibold">
                ⏳ Limit ↓ — Tunggu pullback ke support (Limit Buy)
              </span>
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-orange-100 text-orange-700 border border-orange-200 font-semibold">
                ⏳ Limit ↑ — Tunggu rally ke resistance (Limit Sell)
              </span>
            </div>
            <p className="text-neutral-400 mt-2">
              SL/TP dimonitor otomatis dari harga real Binance setiap 60 detik.
              Simulasi menggunakan 1% risk per trade.
            </p>
          </div>
        </div>
      </div>

      {/* ── Filters row ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Status tabs */}
        <div className="flex gap-1.5 flex-wrap">
          {(["ALL", "open", "tp", "sl"] as FilterTab[]).map(f => (
            <button key={f} onClick={() => setTab(f)}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${
                tab === f
                  ? f === "tp"   ? "bg-green-600 text-white"
                  : f === "sl"   ? "bg-red-600 text-white"
                  : f === "open" ? "bg-neutral-700 text-white"
                  :                "bg-teal-600 text-white"
                  : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200"
              }`}>
              {f === "ALL"  ? `Semua (${counts.ALL})`
               : f === "open" ? `Open (${counts.open})`
               : f === "tp"   ? `TP Hit (${counts.tp})`
               :                `SL Hit (${counts.sl})`}
            </button>
          ))}
        </div>

        {/* Style filter */}
        <div className="flex gap-1.5 flex-wrap">
          {["ALL", "scalping", "daytrading", "swing", "position"].map(s => (
            <button key={s} onClick={() => setStyle(s)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors border ${
                style === s
                  ? "bg-neutral-900 text-white border-neutral-900"
                  : "bg-white text-neutral-500 border-neutral-200 hover:border-neutral-400"
              }`}>
              {s === "ALL" ? "All Styles" : `${STYLE_META[s]?.icon} ${STYLE_META[s]?.label}`}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-400 text-xs">🔍</span>
            <input
              type="text"
              placeholder="Cari symbol…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-7 pr-3 py-1.5 text-xs border border-neutral-200 rounded-lg focus:outline-none focus:border-teal-400 w-36"
            />
          </div>
          {search && (
            <button onClick={() => setSearch("")}
              className="text-xs text-neutral-400 hover:text-neutral-700">✕</button>
          )}
        </div>
      </div>

      {/* ── Result count ────────────────────────────────────────────────────── */}
      {!loading && (
        <p className="text-xs text-neutral-400">
          Menampilkan <strong className="text-neutral-600">{filtered.length}</strong> trade
          {search && <> untuk "<strong className="text-teal-600">{search}</strong>"</>}
          {tab !== "ALL" && <> · filter: <strong className="text-neutral-600">{tab}</strong></>}
        </p>
      )}

      {/* ── Loading ──────────────────────────────────────────────────────────── */}
      {loading && (
        <div className="flex justify-center py-10">
          <span className="animate-spin w-6 h-6 border-2 border-teal-500 border-t-transparent rounded-full" />
        </div>
      )}

      {/* ── Empty state ──────────────────────────────────────────────────────── */}
      {!loading && filtered.length === 0 && (
        <div className="text-center py-12 text-neutral-400">
          <p className="text-3xl mb-2">📋</p>
          <p className="text-sm">Tidak ada trade ditemukan</p>
          <p className="text-xs mt-1">
            {search ? `Tidak ada symbol "${search}"` : "Buka Scanner untuk mulai scan → otomatis tercatat di sini"}
          </p>
        </div>
      )}

      {/* ── Table ────────────────────────────────────────────────────────────── */}
      {filtered.length > 0 && (
        <>
          <div className="overflow-x-auto rounded-xl border border-neutral-100">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] text-neutral-400 bg-neutral-50 border-b border-neutral-100">
                  <th className="text-center py-3 px-3 w-10">#</th>
                  <th className="text-left py-3 px-3">Symbol</th>
                  <th className="text-left py-3 px-2">Style</th>
                  <th className="text-left py-3 px-2">Dir</th>
                  <th className="text-left py-3 px-2">Tipe Entry</th>
                  <th className="text-right py-3 px-2">Entry Price</th>
                  <th className="text-right py-3 px-2">Stop Loss</th>
                  <th className="text-right py-3 px-2">Take Profit</th>
                  <th className="text-center py-3 px-2">R:R</th>
                  <th className="text-center py-3 px-2">Status</th>
                  <th className="text-right py-3 px-2">PnL</th>
                  <th className="text-right py-3 px-3">Waktu</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-50">
                {paginated.map((t, i) => (
                  <TradeRow key={t.id} trade={t} rowNumber={startIndex + i + 1} />
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            page={page}
            totalPages={totalPages}
            totalItems={filtered.length}
            pageSize={PAGE_SIZE}
            onPage={setPage}
          />
        </>
      )}
    </div>
  );
}

// ── Trade Row ─────────────────────────────────────────────────────────────────

function TradeRow({ trade: t, rowNumber }: { trade: PaperTrade; rowNumber: number }) {
  const base       = t.symbol.replace("USDT", "");
  const isLong     = t.direction === "LONG";
  const sc         = STATUS_CONFIG[t.status];
  const sm         = STYLE_META[t.style];
  const em         = ENTRY_TYPE_META[t.entry_type] ?? ENTRY_TYPE_META["market"];
  const hasPnl     = t.pnl_pct !== null;
  const entryDate  = new Date(t.entry_at * 1000).toLocaleDateString(undefined, {
    day: "numeric", month: "short",
  });
  const entryTime  = new Date(t.entry_at * 1000).toLocaleTimeString(undefined, {
    hour: "2-digit", minute: "2-digit",
  });

  return (
    <tr className="hover:bg-teal-50/30 transition-colors group">
      {/* # row number */}
      <td className="py-2.5 px-3 text-center text-[11px] text-neutral-400 font-mono">{rowNumber}</td>

      {/* Symbol */}
      <td className="py-2.5 px-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-teal-50 border border-teal-100 flex items-center justify-center flex-shrink-0">
            <span className="text-[9px] font-black text-teal-600">{base.slice(0, 4)}</span>
          </div>
          <div>
            <p className="font-semibold text-xs group-hover:text-teal-700 transition-colors">{base}/USDT</p>
            {t.signals?.[0] && (
              <p className="text-[10px] text-neutral-400 truncate max-w-[120px]">{t.signals[0]}</p>
            )}
          </div>
        </div>
      </td>

      {/* Style */}
      <td className="py-2.5 px-2">
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${sm?.badge ?? ""}`}>
          {sm?.icon} {sm?.label}
        </span>
      </td>

      {/* Direction */}
      <td className="py-2.5 px-2">
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
          isLong ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
        }`}>
          {isLong ? "▲ LONG" : "▼ SHORT"}
        </span>
      </td>

      {/* Entry type */}
      <td className="py-2.5 px-2">
        <span title={em.tip}
          className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border cursor-help ${em.badge}`}>
          {em.label}
        </span>
      </td>

      {/* Entry price */}
      <td className="py-2.5 px-2 text-right font-mono text-xs font-semibold">
        ${fmtPrice(t.entry_price)}
      </td>

      {/* Stop Loss */}
      <td className="py-2.5 px-2 text-right font-mono text-xs text-red-500">
        ${fmtPrice(t.stop_loss)}
      </td>

      {/* Take Profit */}
      <td className="py-2.5 px-2 text-right font-mono text-xs text-green-600">
        ${fmtPrice(t.take_profit)}
      </td>

      {/* R:R */}
      <td className="py-2.5 px-2 text-center">
        <span className="text-xs font-bold text-teal-600">{t.risk_reward}</span>
      </td>

      {/* Status */}
      <td className="py-2.5 px-2 text-center">
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${sc.bg} ${sc.color}`}>
          {sc.label}
        </span>
      </td>

      {/* PnL */}
      <td className="py-2.5 px-2 text-right">
        {hasPnl ? (
          <span className={`text-xs font-bold ${t.pnl_pct! >= 0 ? "text-green-600" : "text-red-500"}`}>
            {t.pnl_pct! >= 0 ? "+" : ""}{t.pnl_pct!.toFixed(2)}%
          </span>
        ) : (
          <span className="text-xs text-neutral-300">—</span>
        )}
      </td>

      {/* Time */}
      <td className="py-2.5 px-3 text-right">
        <p className="text-[10px] text-neutral-500">{entryDate}</p>
        <p className="text-[10px] text-neutral-400">{entryTime}</p>
      </td>
    </tr>
  );
}
