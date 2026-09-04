"use client";
import { apiFetch } from "@/lib/api";
import { useEffect, useState, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Pagination } from "@/components/ui/pagination";
import { MarketTable } from "./market/MarketTable";
import { getCoinCategory, ALL_CATEGORIES } from "../data/categories";

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
  const [tickers, setTickers]           = useState<FuturesTicker[]>([]);
  const [loading, setLoading]           = useState(true);
  const [category, setCategory]         = useState("All");
  const [search, setSearch]             = useState("");
  const [page, setPage]                 = useState(1);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiFetch("/api/v1/market/futures-market");
      const d   = await res.json();
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
    return tickers.filter(t => {
      const matchSearch = t.symbol.toLowerCase().includes(search.toLowerCase());
      const matchCat    = category === "All" || getCoinCategory(t.symbol) === category;
      return matchSearch && matchCat;
    });
  }, [tickers, category, search]);

  useMemo(() => { setPage(1); }, [filtered.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated  = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

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
                onChange={e => setSearch(e.target.value)}
                className="text-sm border rounded-lg px-3 py-1.5 w-36 focus:outline-none focus:border-primarygreen"
              />
            </div>
          </CardTitle>

          {/* Category tabs */}
          <div className="flex gap-1.5 flex-wrap mt-2">
            {ALL_CATEGORIES.map(cat => (
              <button key={cat} onClick={() => setCategory(cat)}
                className={`px-3 py-1 rounded-full text-xs font-semibold transition-colors border ${
                  category === cat
                    ? "bg-primarygreen text-white border-primarygreen"
                    : "bg-neutral-50 text-neutral-600 border-neutral-200 hover:border-primarygreen hover:text-primarygreen"
                }`}>
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
            <MarketTable
              tickers={paginated}
              startIndex={(page - 1) * PAGE_SIZE}
            />
          )}

          <Pagination
            page={page}
            totalPages={totalPages}
            totalItems={filtered.length}
            pageSize={PAGE_SIZE}
            onPage={setPage}
          />
        </CardContent>
      </Card>
    </>
  );
}
