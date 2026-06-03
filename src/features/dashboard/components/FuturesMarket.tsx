"use client";
import { useEffect, useState, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getCoinCategory, ALL_CATEGORIES } from "../data/categories";
import { CoinModal } from "./CoinModal";

interface FuturesTicker {
  symbol: string;
  price: number;
  change_24h: number;
  volume_24h: number;
  high_24h: number;
  low_24h: number;
}

const PAGE_SIZE = 50;

export function FuturesMarket() {
  const [tickers, setTickers] = useState<FuturesTicker[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("All");
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/v1/market/futures-market");
      const d = await res.json();
      setTickers(d.tickers ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(() => void fetchData(), 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const filtered = useMemo(() => {
    return tickers.filter((t) => {
      const matchSearch = t.symbol.toLowerCase().includes(search.toLowerCase());
      const matchCat = category === "All" || getCoinCategory(t.symbol) === category;
      return matchSearch && matchCat;
    });
  }, [tickers, category, search]);

  // Reset to page 1 when filter/search changes
  useMemo(() => { setPage(1); }, [filtered.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const fmtVol = (v: number) =>
    v >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : `${(v / 1e3).toFixed(0)}K`;

  const fmtPrice = (p: number) =>
    p < 0.001 ? p.toFixed(6) : p < 1 ? p.toFixed(4) : p.toLocaleString(undefined, { maximumFractionDigits: 2 });

  // Category counts
  const catCounts = useMemo(() => {
    const counts: Record<string, number> = { All: tickers.length };
    for (const t of tickers) {
      const c = getCoinCategory(t.symbol);
      counts[c] = (counts[c] ?? 0) + 1;
    }
    return counts;
  }, [tickers]);

  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center justify-between flex-wrap gap-2">
            <span>Futures Market — 24h Change</span>
            <div className="flex items-center gap-2">
              {!loading && (
                <span className="text-xs text-muted-foreground font-normal">
                  {filtered.length}/{tickers.length} pairs
                </span>
              )}
              <input
                type="text"
                placeholder="Search coin..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="text-sm border rounded-lg px-3 py-1.5 w-36 focus:outline-none focus:border-primarygreen"
              />
            </div>
          </CardTitle>

          {/* Category tabs */}
          <div className="flex gap-1.5 flex-wrap mt-2">
            {ALL_CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors border ${
                  category === cat
                    ? "bg-primarygreen text-white border-primarygreen"
                    : "bg-neutral-50 text-neutral-600 border-neutral-200 hover:border-primarygreen hover:text-primarygreen"
                }`}
              >
                {cat}
                {catCounts[cat] !== undefined && (
                  <span className={`ml-1 ${category === cat ? "opacity-80" : "text-muted-foreground"}`}>
                    {catCounts[cat]}
                  </span>
                )}
              </button>
            ))}
          </div>
        </CardHeader>

        <CardContent className="pt-0">
          {loading && tickers.length === 0 && (
            <div className="flex items-center justify-center py-10">
              <span className="animate-spin w-6 h-6 border-2 border-primarygreen border-t-transparent rounded-full" />
            </div>
          )}

          {!loading && filtered.length === 0 && (
            <p className="text-center text-muted-foreground py-8 text-sm">No coins found</p>
          )}

          {filtered.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b">
                    <th className="text-left py-2 pr-3 pl-1">#</th>
                    <th className="text-left py-2 pr-3">Symbol</th>
                    <th className="text-left py-2 pr-3">Category</th>
                    <th className="text-right py-2 pr-3">Price</th>
                    <th className="text-right py-2 pr-3">24h %</th>
                    <th className="text-right py-2 pr-3">Volume</th>
                    <th className="text-right py-2 pr-3">High</th>
                    <th className="text-right py-2">Low</th>
                  </tr>
                </thead>
                <tbody>
                  {paginated.map((t, i) => {
                    const base = t.symbol.replace("USDT", "");
                    const cat = getCoinCategory(t.symbol);
                    const globalIdx = (page - 1) * PAGE_SIZE + i + 1;
                    return (
                      <tr
                        key={t.symbol}
                        onClick={() => setSelectedSymbol(t.symbol)}
                        className="border-b border-neutral-50 hover:bg-teal-50 cursor-pointer transition-colors group"
                      >
                        <td className="py-2.5 pr-3 pl-1 text-muted-foreground text-xs">{globalIdx}</td>
                        <td className="py-2.5 pr-3">
                          <div className="flex items-center gap-2">
                            <div className="w-7 h-7 rounded-full bg-primarygreen/10 flex items-center justify-center flex-shrink-0">
                              <span className="text-[10px] font-bold text-primarygreen">{base.slice(0, 3)}</span>
                            </div>
                            <div>
                              <span className="font-semibold group-hover:text-primarygreen transition-colors">{base}</span>
                              <span className="text-xs text-muted-foreground">/USDT</span>
                            </div>
                          </div>
                        </td>
                        <td className="py-2.5 pr-3">
                          <span className="text-xs bg-neutral-100 text-neutral-600 px-2 py-0.5 rounded-full">{cat}</span>
                        </td>
                        <td className="py-2.5 pr-3 text-right font-mono text-xs font-semibold">
                          ${fmtPrice(t.price)}
                        </td>
                        <td className={`py-2.5 pr-3 text-right font-bold text-sm ${t.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
                          {t.change_24h >= 0 ? "▲" : "▼"} {Math.abs(t.change_24h).toFixed(2)}%
                        </td>
                        <td className="py-2.5 pr-3 text-right text-xs text-muted-foreground">
                          ${fmtVol(t.volume_24h)}
                        </td>
                        <td className="py-2.5 pr-3 text-right text-xs text-green-600 font-mono">
                          ${fmtPrice(t.high_24h)}
                        </td>
                        <td className="py-2.5 text-right text-xs text-red-500 font-mono">
                          ${fmtPrice(t.low_24h)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4 pt-3 border-t">
              <span className="text-xs text-muted-foreground">
                {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}
              </span>
              <div className="flex gap-1 items-center">
                <button onClick={() => setPage(1)} disabled={page === 1}
                  className="px-2 py-1 text-xs rounded border disabled:opacity-30 hover:bg-neutral-50">«</button>
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                  className="px-2.5 py-1 text-xs rounded border disabled:opacity-30 hover:bg-neutral-50">‹</button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  const start = Math.max(1, Math.min(page - 2, totalPages - 4));
                  const p = start + i;
                  return (
                    <button key={p} onClick={() => setPage(p)}
                      className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                        p === page ? "bg-primarygreen text-white border-primarygreen" : "hover:bg-neutral-50"
                      }`}>
                      {p}
                    </button>
                  );
                })}
                <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}
                  className="px-2.5 py-1 text-xs rounded border disabled:opacity-30 hover:bg-neutral-50">›</button>
                <button onClick={() => setPage(totalPages)} disabled={page === totalPages}
                  className="px-2 py-1 text-xs rounded border disabled:opacity-30 hover:bg-neutral-50">»</button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Coin Modal */}
      {selectedSymbol && (
        <CoinModal symbol={selectedSymbol} onClose={() => setSelectedSymbol(null)} />
      )}
    </>
  );
}
