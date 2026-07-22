"use client";
import { useMemo, useState } from "react";
import type { OppPosition, OppStats } from "./OppSpotTypes";
import { OpenPositionCard } from "./OpenPositionCard";

const PAGE_SIZE = 5;
// PLAN_SPOT_LANES audit 22 Jul: kartu ini dulu menulis "maks 3 posisi bersamaan"
// — kebijakan yang TIDAK ADA di kode. `MAX_OPENS_PER_CYCLE = 3` membatasi entri
// BARU per siklus scan (3 menit), bukan jumlah posisi terbuka. Satu-satunya rem
// jumlah posisi adalah modal: entri ditolak saat sisa saldo tak cukup mendanai
// notional penuh. Label diluruskan supaya layar tidak menjanjikan pengaman fiktif.
const MAX_OPENS_PER_CYCLE = 3;

interface OpenPositionsListProps {
  openList:  OppPosition[];
  stats:     Pick<
    OppStats,
    | "totalRisk$"
    | "riskDollar"
    | "totalNotional$"
    | "availableBalance$"
    | "currentBalance"
    | "maxConcurrent"
  >;
  closingId: number | null;
  onClose:   (id: number, symbol: string) => void;
}

export function OpenPositionsList({ openList, stats, closingId, onClose }: OpenPositionsListProps) {
  const [page, setPage] = useState(1);

  const totalPages = Math.max(1, Math.ceil(openList.length / PAGE_SIZE));
  // Clamp saat render — jumlah posisi bisa berubah tiap poll (tanpa setState di effect)
  const safePage = Math.min(page, totalPages);

  // Urut default: unrealized P&L tertinggi dulu
  const sorted = useMemo(
    () => [...openList].sort(
      (a, b) => (b.unrealized_pnl_pct ?? -999) - (a.unrealized_pnl_pct ?? -999)
    ),
    [openList]
  );
  const pageItems = sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  if (openList.length === 0) return null;

  const overAllocated = stats.availableBalance$ < 0;

  return (
    <div className="bg-blue-50 border border-blue-100 rounded-2xl overflow-hidden">
      {/* Header — agregat SEMUA posisi, bukan per halaman */}
      <div className="px-4 py-3 border-b border-blue-100">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h3 className="font-bold text-sm text-blue-700">
            🔵 Posisi Terbuka ({openList.length})
          </h3>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] text-blue-600 font-semibold">
              Risk:{" "}
              <strong className="text-yellow-600">${stats.totalRisk$.toFixed(2)}</strong>
              {" "}({openList.length} posisi)
            </span>
            <span className="text-[10px] text-neutral-400">·</span>
            <span className="text-[10px] font-semibold">
              Notional:{" "}
              <strong className={overAllocated ? "text-red-600" : "text-neutral-700"}>
                ${stats.totalNotional$.toFixed(0)}
              </strong>
            </span>
            <span className="text-[10px] text-neutral-400">·</span>
            <span className={`text-[10px] font-semibold ${overAllocated ? "text-red-600" : "text-green-600"}`}>
              Sisa: ${Math.max(0, stats.availableBalance$).toFixed(0)}
            </span>
          </div>
        </div>

        {overAllocated ? (
          <div className="mt-1.5 text-[10px] bg-red-50 border border-red-200 rounded-lg px-2.5 py-1.5 text-red-700">
            ⚠️{" "}
            <strong>
              Total notional (${stats.totalNotional$.toFixed(0)}) melebihi balance
              (${stats.currentBalance.toFixed(0)})
            </strong>
            {" "}— posisi legacy; agent tidak akan menambah posisi sampai modal kembali normal.
          </div>
        ) : (
          <p className="mt-1 text-[10px] text-neutral-400">
            Modal tersisa{" "}
            <strong className="text-neutral-600">${stats.availableBalance$.toFixed(0)}</strong>
            {" "}· Kebijakan: maks <strong>{MAX_OPENS_PER_CYCLE} entri baru</strong> per siklus scan.
            Jumlah posisi terbuka dibatasi <strong>modal</strong>, bukan angka tetap —
            entri ditolak saat sisa saldo tak cukup mendanai notional penuh.
          </p>
        )}
      </div>

      {/* Kartu per halaman */}
      <div className="divide-y divide-blue-100">
        {pageItems.map(p => (
          <OpenPositionCard
            key={p.id}
            position={p}
            riskDollar={stats.riskDollar}
            closingId={closingId}
            onClose={onClose}
          />
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-blue-100 bg-blue-50/50">
          <span className="text-[10px] text-neutral-500">
            Menampilkan {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, openList.length)} dari {openList.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={safePage === 1}
              className="text-[11px] font-bold px-2 py-1 rounded-lg border border-blue-200 text-blue-600 disabled:opacity-30 hover:bg-blue-100"
            >
              ‹ Prev
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1)
              .filter(n => n === 1 || n === totalPages || Math.abs(n - safePage) <= 1)
              .map((n, idx, arr) => (
                <span key={n} className="flex items-center">
                  {idx > 0 && arr[idx - 1] !== n - 1 && (
                    <span className="text-[10px] text-neutral-400 px-0.5">…</span>
                  )}
                  <button
                    onClick={() => setPage(n)}
                    className={`text-[11px] font-bold w-6 h-6 rounded-lg ${
                      n === safePage
                        ? "bg-blue-600 text-white"
                        : "text-blue-600 hover:bg-blue-100"
                    }`}
                  >
                    {n}
                  </button>
                </span>
              ))}
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={safePage === totalPages}
              className="text-[11px] font-bold px-2 py-1 rounded-lg border border-blue-200 text-blue-600 disabled:opacity-30 hover:bg-blue-100"
            >
              Next ›
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
