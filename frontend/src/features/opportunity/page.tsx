"use client";
import { apiFetch, HEAVY_TIMEOUT_MS } from "@/lib/api";
import { useCallback, useEffect, useState, useMemo, useRef } from "react";
import { Card } from "@/components/ui/card";
import {
  OpportunityFeatured,
  OpportunityRow,
  OpportunityResult,
} from "./components/OpportunityCard";
import { CoinModal } from "./components/CoinModal";
import { MarketIntelBanner } from "@/components/MarketIntelBanner";
import { type ConnState, CONN_META } from "@/components/ui/live-badge";

// §11.6: WS URL dinamis — ikut host & protokol halaman (wss saat https)
function wsUrl(): string {
  if (typeof window === "undefined") return "ws://localhost:8000/ws/opportunity";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.hostname}:8000/ws/opportunity`;
}

const RECONNECT_MS   = 3000;
const TOP_FEATURED   = 5;
const INTERVAL_SEC   = 3 * 60;

// Phase 3 G3-regime: 3-state BTC gate
type RegimeStatus = "OPEN" | "REDUCED" | "CLOSED";

// §11.1: aturan engine diambil dari API — UI tidak boleh hardcode angka aturan
interface ScannerConfig {
  min_score:          number;
  auto_open_score:    number;
  rr_min:             number;
  sl_buffer_pct:      number;
  tp2_rule:           string;
  tp3_rule:           string;
  execution_cost_pct: number;
  direction_gate:     string;
  max_concurrent:     number;
}

const ALERT_FILTERS = [
  { key: "ALL",           label: "Semua" },
  { key: "squeeze",       label: "⚡ Squeeze" },
  { key: "accumulation",  label: "📦 Akumulasi" },
  { key: "breakout_pump", label: "🚀 Breakout" },
];

function fmtCountdown(secs: number | null): string {
  if (secs === null) return "--:--";
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function timeAgo(date: Date | null): string {
  if (!date) return "";
  const secs = Math.floor((Date.now() - date.getTime()) / 1000);
  if (secs < 10)  return "baru saja";
  if (secs < 60)  return `${secs} dtk lalu`;
  const m = Math.floor(secs / 60);
  if (m < 60) return `${m} mnt lalu`;
  return `${Math.floor(m / 60)} jam lalu`;
}

// ── Active positions type (minimal) ──────────────────────────────────────────
interface ActivePos {
  id: number; symbol: string; entry: number;
  current_price: number | null; unrealized_pnl_pct: number | null;
  tp1_hit: boolean;
}

export default function OpportunityPage() {
  const [results, setResults]         = useState<OpportunityResult[]>([]);
  const [loading, setLoading]         = useState(true);
  const [connState, setConnState]     = useState<ConnState>("connecting");
  const [scanning, setScanning]       = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [scanned, setScanned]         = useState(0);
  const [elapsed, setElapsed]         = useState(0);
  const [alertFilter, setAlert]       = useState("ALL");
  const [search, setSearch]           = useState("");
  const [minScore, setMinScore]       = useState(0);
  const [config, setConfig]           = useState<ScannerConfig | null>(null);
  const [isLive, setIsLive]           = useState(true);
  const [newSymbols, setNewSymbols]   = useState<Set<string>>(new Set());
  const [timeAgoStr, setTimeAgoStr]   = useState("");
  const [selectedCoin, setSelectedCoin] = useState<OpportunityResult | null>(null);
  // Phase 3 G3-regime: BTC regime state for banner
  const [regimeStatus, setRegimeStatus] = useState<RegimeStatus>("OPEN");
  const [btcChange24h, setBtcChange24h] = useState<number | null>(null);

  // Active positions banner
  const [activePositions, setActivePositions] = useState<ActivePos[]>([]);

  // Fetch active open positions for the banner (poll every 30s)
  const fetchActivePositions = useCallback(async () => {
    try {
      const r = await apiFetch("/api/v1/opportunity/positions");
      if (!r.ok) return;
      const d = await r.json() as { positions: ActivePos[] };
      setActivePositions(d.positions.filter(p => (p as unknown as { status: string }).status === "open"));
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    void fetchActivePositions();
    const t = setInterval(() => void fetchActivePositions(), 30_000);
    return () => clearInterval(t);
  }, [fetchActivePositions]);

  // §11.1: ambil aturan engine sekali — header & legend render dari sini
  useEffect(() => {
    void (async () => {
      try {
        const r = await apiFetch("/api/v1/opportunity/config");
        if (r.ok) setConfig(await r.json() as ScannerConfig);
      } catch { /* fallback: teks generik tanpa angka */ }
    })();
  }, []);

  // Countdown uses a ref so the interval never restarts
  const nextScanInRef = useRef<number | null>(null);
  const [nextScanDisplay, setNextScanDisplay] = useState<number | null>(null);
  const prevSymbolsRef = useRef<Set<string>>(new Set());

  // Tick countdown every second
  useEffect(() => {
    const timer = setInterval(() => {
      if (nextScanInRef.current !== null && nextScanInRef.current > 0) {
        nextScanInRef.current--;
        setNextScanDisplay(nextScanInRef.current);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Update "X min ago" display every 10s
  useEffect(() => {
    const timer = setInterval(() => {
      setTimeAgoStr(prev => {
        const next = timeAgo(lastUpdated);
        return next !== prev ? next : prev;
      });
    }, 10_000);
    setTimeAgoStr(timeAgo(lastUpdated));
    return () => clearInterval(timer);
  }, [lastUpdated]);

  const applySnapshot = useCallback((data: Record<string, unknown>) => {
    const raw = (data.results ?? []) as OpportunityResult[];

    const currentSet = new Set(raw.map(r => r.symbol));
    const prev = prevSymbolsRef.current;
    const fresh = new Set<string>();
    if (prev.size > 0) {
      currentSet.forEach(s => { if (!prev.has(s)) fresh.add(s); });
    }
    prevSymbolsRef.current = currentSet;

    setResults(raw);
    setScanned((data.scanned as number) ?? 0);
    setElapsed((data.elapsed_sec as number) ?? 0);
    setLastUpdated(new Date());
    setTimeAgoStr("baru saja");
    setLoading(false);
    setScanning(false);
    // Phase 3 G3-regime: surface BTC regime status for banner
    setRegimeStatus((data.regime_status as RegimeStatus) ?? "OPEN");
    setBtcChange24h((data.btc_change_24h as number) ?? null);

    if (typeof data.next_scan_in === "number") {
      nextScanInRef.current = data.next_scan_in;
      setNextScanDisplay(data.next_scan_in);
    }

    if (fresh.size > 0) {
      setNewSymbols(fresh);
      setTimeout(() => setNewSymbols(new Set()), 8000);
    }
  }, []);

  // WebSocket lifecycle
  useEffect(() => {
    if (!isLive) {
      setConnState("paused");
      return;
    }

    let mounted = true;
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    function connect() {
      if (!mounted) return;
      setConnState("connecting");
      ws = new WebSocket(wsUrl());

      ws.onopen = () => { if (mounted) setConnState("connected"); };

      ws.onmessage = (e) => {
        if (!mounted) return;
        try {
          const msg = JSON.parse(e.data as string) as Record<string, unknown>;
          if (msg.type === "snapshot") {
            applySnapshot(msg);
          } else if (msg.type === "heartbeat") {
            setScanning((msg.scanning as boolean) ?? false);
            if (typeof msg.next_scan_in === "number") {
              nextScanInRef.current = msg.next_scan_in;
              setNextScanDisplay(msg.next_scan_in);
            }
          } else if (msg.type === "scanning") {
            setScanning((msg.scanning as boolean) ?? true);
          } else if (msg.type === "status") {
            setLoading(false);
          }
        } catch { /* ignore bad JSON */ }
      };

      ws.onclose = () => {
        if (!mounted) return;
        setConnState("reconnecting");
        reconnectTimer = setTimeout(connect, RECONNECT_MS);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      mounted = false;
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [isLive, applySnapshot]);

  // Trigger fresh scan — backend auto-detects old cache and runs new scan (~25s)
  const manualScan = useCallback(async () => {
    setScanning(true);
    try {
      // §11.7: tanpa parameter mati — engine sudah memfilter via MIN_SCORE
      const r = await apiFetch("/api/v1/opportunity/scan?limit=50", { method: "POST", timeoutMs: HEAVY_TIMEOUT_MS });
      if (!r.ok) return;
      const d = await r.json() as Record<string, unknown>;
      applySnapshot(d);
    } catch { /* silent */ }
    finally { setScanning(false); }
  }, [applySnapshot]);

  // Filters — breakout_pump always shown in dedicated section below, not in main list
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return results.filter(r => {
      if (r.alert_type === "breakout_pump") return false;
      if (alertFilter !== "ALL" && r.alert_type !== alertFilter) return false;
      if (r.opportunity_score < minScore) return false;
      if (q && !r.symbol.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [results, alertFilter, minScore, search]);

  const filteredBreakout = useMemo(() => {
    const q = search.trim().toLowerCase();
    return results.filter(r => {
      if (r.alert_type !== "breakout_pump") return false;
      if (q && !r.symbol.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [results, search]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { ALL: results.filter(r => r.alert_type !== "breakout_pump").length };
    results.forEach(r => { c[r.alert_type] = (c[r.alert_type] ?? 0) + 1; });
    return c;
  }, [results]);

  const autoThreshold = config?.auto_open_score ?? 90;
  const highCount  = results.filter(r => r.auto_open || r.opportunity_score >= autoThreshold).length;
  const watchCount = results.filter(r => !r.auto_open && r.opportunity_score < autoThreshold).length;
  const featured   = filtered.slice(0, TOP_FEATURED);
  const rest       = filtered.slice(TOP_FEATURED);

  const cm = CONN_META[connState];
  const scanProgress = nextScanDisplay !== null
    ? Math.round(((INTERVAL_SEC - nextScanDisplay) / INTERVAL_SEC) * 100)
    : 0;

  return (
    <div className="space-y-4">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="rounded-2xl bg-gradient-to-br from-neutral-900 via-neutral-800 to-neutral-900 text-white overflow-hidden">

        {/* Scan progress bar */}
        <div className="h-0.5 bg-neutral-700 w-full">
          <div
            className="h-full bg-teal-500 transition-all duration-1000 ease-linear"
            style={{ width: `${scanProgress}%` }}
          />
        </div>

        <div className="p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">

            {/* Left */}
            <div>
              <div className="flex items-center gap-3 mb-1.5">
                <span className="text-3xl">🚀</span>
                <div>
                  <h1 className="text-2xl font-bold leading-tight">Opportunity Scanner</h1>
                  <p className="text-xs text-neutral-400">
                    Rekomendasi posisi SPOT · Entry · SL · TP
                    {config && <> · R:R ≥ {config.rr_min}</>}
                  </p>
                </div>
              </div>
              <p className="text-xs text-neutral-500 max-w-md leading-relaxed ml-12">
                Setup risk-adjusted: ranking berdasarkan expected value per unit risk,
                size mengikuti balance real, biaya eksekusi
                {config ? ` ${config.execution_cost_pct}%` : ""} sudah diperhitungkan.
              </p>

              {/* §11.1: legend dari aturan engine yang SEBENARNYA */}
              <div className="flex gap-2 mt-3 ml-12 flex-wrap">
                {(config ? [
                  { dot: "bg-red-400",   label: `SL · swing low −${config.sl_buffer_pct}%` },
                  { dot: "bg-green-400", label: `TP2 · ${config.tp2_rule}` },
                  { dot: "bg-green-200", label: `TP3 · ${config.tp3_rule}` },
                  { dot: "bg-teal-400",  label: `🤖 auto ≥ ${config.auto_open_score}pt + arah` },
                ] : [
                  { dot: "bg-neutral-500", label: "memuat aturan engine…" },
                ]).map(l => (
                  <span key={l.label} className="flex items-center gap-1.5 text-[10px] text-neutral-400 bg-white/5 px-2.5 py-1 rounded-full border border-white/10">
                    <span className={`w-1.5 h-1.5 rounded-full ${l.dot}`} />
                    {l.label}
                  </span>
                ))}
              </div>
            </div>

            {/* Right */}
            <div className="flex flex-col items-end gap-3">

              {/* Connection + scanning status */}
              <div className="flex items-center gap-2 flex-wrap justify-end">
                <button
                  onClick={() => setIsLive(v => !v)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-bold border transition-all ${cm.color}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${cm.dot}`} />
                  {cm.label}
                </button>

                {scanning && (
                  <span className="flex items-center gap-1.5 text-[11px] text-teal-300 bg-teal-500/10 border border-teal-500/30 px-3 py-1.5 rounded-full">
                    <span className="w-2 h-2 rounded-full bg-teal-400 animate-ping" />
                    Scanning 100 pairs...
                  </span>
                )}

                {!scanning && nextScanDisplay !== null && connState === "connected" && (
                  <span className="text-[11px] text-neutral-400 font-mono tabular-nums">
                    next scan <strong className="text-neutral-200">{fmtCountdown(nextScanDisplay)}</strong>
                  </span>
                )}
              </div>

              {/* Stats */}
              <div className="flex gap-2">
                <div className="bg-green-500/15 border border-green-500/25 rounded-xl px-3.5 py-2 text-center min-w-[60px]">
                  <p className="text-green-400 font-black text-2xl leading-tight">{highCount}</p>
                  <p className="text-[9px] text-green-500/80 mt-0.5">🤖 AUTO</p>
                </div>
                <div className="bg-yellow-500/15 border border-yellow-500/25 rounded-xl px-3.5 py-2 text-center min-w-[60px]">
                  <p className="text-yellow-400 font-black text-2xl leading-tight">{watchCount}</p>
                  <p className="text-[9px] text-yellow-500/80 mt-0.5">⚡ WATCH</p>
                </div>
                <div className="bg-neutral-700/50 border border-neutral-600/50 rounded-xl px-3.5 py-2 text-center min-w-[60px]">
                  <p className="text-neutral-200 font-black text-2xl leading-tight">{scanned}</p>
                  <p className="text-[9px] text-neutral-500 mt-0.5">pairs</p>
                </div>
              </div>

              {/* Last updated + scan button */}
              <div className="flex items-center gap-2">
                {lastUpdated && (
                  <div className="text-right">
                    <p className="text-[10px] text-neutral-400 tabular-nums">
                      {lastUpdated.toLocaleTimeString()}
                      {elapsed > 0 && <span className="text-neutral-600"> · {elapsed.toFixed(1)}s</span>}
                    </p>
                    <p className="text-[10px] text-neutral-600">{timeAgoStr}</p>
                  </div>
                )}
                <button
                  onClick={() => void manualScan()}
                  disabled={scanning}
                  className="text-xs bg-teal-600 hover:bg-teal-500 disabled:opacity-40 px-3 py-1.5 rounded-lg transition-colors font-semibold whitespace-nowrap"
                >
                  {scanning ? (
                    <span className="flex items-center gap-1.5">
                      <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      Scanning...
                    </span>
                  ) : "⚡ Scan Sekarang"}
                </button>
              </div>

            </div>
          </div>
        </div>
      </div>

      {/* ── Active positions banner ────────────────────────────────────────── */}
      {activePositions.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap px-3 py-2 bg-neutral-900 rounded-xl">
          <span className="text-[10px] text-neutral-400 font-semibold shrink-0">
            💼 {activePositions.length} posisi aktif:
          </span>
          {activePositions.map(p => {
            const upnl = p.unrealized_pnl_pct;
            const isProfit = upnl != null && upnl >= 0;
            const isLoss   = upnl != null && upnl < 0;
            return (
              <span
                key={p.id}
                className={`flex items-center gap-1 text-[11px] font-bold px-2.5 py-1 rounded-lg ${
                  p.tp1_hit   ? "bg-yellow-900/60 text-yellow-300 border border-yellow-700/50" :
                  isProfit    ? "bg-green-900/60 text-green-300 border border-green-700/50" :
                  isLoss      ? "bg-red-900/60 text-red-300 border border-red-700/50" :
                                "bg-neutral-700 text-neutral-300 border border-neutral-600"
                }`}
              >
                <span>{p.symbol.replace("USDT", "")}</span>
                {p.tp1_hit && <span className="text-[9px]">🟡TP1</span>}
                {upnl != null ? (
                  <span className="text-[10px]">{upnl >= 0 ? "+" : ""}{upnl.toFixed(2)}%</span>
                ) : (
                  <span className="text-[10px] opacity-50">—</span>
                )}
              </span>
            );
          })}
          <span className="text-[10px] text-neutral-600 ml-auto">
            Tutup posisi di History →
          </span>
        </div>
      )}

      {/* ── Filter bar ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        {ALERT_FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setAlert(f.key)}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-all ${
              alertFilter === f.key
                ? "bg-teal-600 text-white shadow-sm"
                : "bg-white border border-neutral-200 text-neutral-600 hover:border-teal-300 hover:text-teal-600"
            }`}
          >
            {f.label}
            <span className={`ml-1.5 text-[10px] ${alertFilter === f.key ? "text-teal-200" : "text-neutral-400"}`}>
              ({counts[f.key] ?? 0})
            </span>
          </button>
        ))}

        {/* §11.2: opsi filter dari threshold engine — tidak ada pilihan mati */}
        <div className="flex items-center gap-1.5 bg-white border border-neutral-200 rounded-full px-3 py-1.5">
          <span className="text-neutral-400 text-[10px] font-semibold">MIN</span>
          <select
            value={minScore}
            onChange={e => setMinScore(Number(e.target.value))}
            className="text-xs text-neutral-700 bg-transparent focus:outline-none cursor-pointer"
          >
            <option value={0}>Semua (≥{config?.min_score ?? 65}pt)</option>
            <option value={80}>80pt ⚡</option>
            <option value={config?.auto_open_score ?? 90}>
              {config?.auto_open_score ?? 90}pt 🤖
            </option>
          </select>
        </div>

        <div className="relative flex-1 min-w-[140px] max-w-[200px]">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400 text-xs">🔍</span>
          <input
            type="text"
            placeholder="Cari koin…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-white border border-neutral-200 rounded-full text-xs focus:outline-none focus:border-teal-400 transition-colors"
          />
        </div>

        {(alertFilter !== "ALL" || minScore > 30 || search) && (
          <button
            onClick={() => { setAlert("ALL"); setMinScore(30); setSearch(""); }}
            className="text-xs text-neutral-400 hover:text-neutral-600 underline"
          >
            Reset
          </button>
        )}

        <span className="text-xs text-neutral-400 ml-auto tabular-nums">
          {filtered.length} dari {results.length} hasil
        </span>
      </div>

      {/* ── Market Intel Banner ──────────────────────────────────────────────── */}
      <MarketIntelBanner mode="spot" />

      {regimeStatus !== "OPEN" && (
        <div
          className={`rounded-xl border px-4 py-2.5 text-sm flex items-center gap-2 ${
            regimeStatus === "CLOSED"
              ? "bg-red-50 border-red-200 text-red-700"
              : "bg-amber-50 border-amber-200 text-amber-800"
          }`}
        >
          <span className="text-base">
            {regimeStatus === "CLOSED" ? "🛑" : "⚠️"}
          </span>
          <div className="flex-1">
            <span className="font-bold">
              Regime: {regimeStatus}
            </span>
            <span className="ml-2 text-xs opacity-80">
              {regimeStatus === "CLOSED"
                ? "Auto-open dimatikan — BTC turun tajam (≤−5%/24h)."
                : "Sistem konservatif — quota auto-open dipotong ke 1/cycle."}
              {btcChange24h !== null && ` BTC 24h ${btcChange24h >= 0 ? "+" : ""}${btcChange24h.toFixed(2)}%`}
            </span>
          </div>
        </div>
      )}

      {/* ── Score legend ───────────────────────────────────────────────────── */}
      {!loading && filtered.length > 0 && (
        <div className="flex items-center gap-3 flex-wrap px-1">
          {[
            { bg: "bg-neutral-900", emoji: "🤖", label: `≥ ${config?.auto_open_score ?? 90} Auto-open` },
            { bg: "bg-green-500",   emoji: "🔥", label: `80–${(config?.auto_open_score ?? 90) - 1} High` },
            { bg: "bg-yellow-500",  emoji: "⚡", label: `${config?.min_score ?? 65}–79 Watch` },
          ].map(l => (
            <span key={l.label} className="flex items-center gap-1.5 text-xs text-neutral-500">
              <span className={`${l.bg} text-white text-[10px] font-bold px-2 py-0.5 rounded-full`}>
                {l.emoji} {l.label}
              </span>
            </span>
          ))}
          {newSymbols.size > 0 && (
            <span className="flex items-center gap-1.5 text-xs text-teal-600 font-semibold animate-pulse">
              <span className="w-2 h-2 rounded-full bg-teal-400 shrink-0" />
              {newSymbols.size} koin baru terdeteksi
            </span>
          )}
        </div>
      )}

      {/* ── Loading ────────────────────────────────────────────────────────── */}
      {loading && !results.length && (
        <div className="py-20 text-center">
          <div className="space-y-3">
            <div className="w-14 h-14 rounded-full bg-teal-100 flex items-center justify-center mx-auto">
              <span className="text-3xl animate-bounce">🚀</span>
            </div>
            <p className="font-semibold text-neutral-700">Menghubungkan ke scanner...</p>
            <p className="text-xs text-neutral-400">Menganalisis BB Squeeze + Volume + RSI di 15m, 1H, 4H</p>
          </div>
        </div>
      )}

      {/* ── Featured cards ─────────────────────────────────────────────────── */}
      {!loading && featured.length > 0 && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
            {featured.map((r, i) => (
              <OpportunityFeatured
                key={r.symbol}
                r={r}
                rank={i + 1}
                isNew={newSymbols.has(r.symbol)}
                onClick={() => setSelectedCoin(r)}
              />
            ))}
          </div>

          {rest.length > 0 && (
            <Card className="overflow-hidden border-neutral-200">
              <div className="flex items-center gap-3 px-4 py-2.5 bg-neutral-50 border-b text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
                <span className="w-6">#</span>
                <span className="w-10">Skor</span>
                <span className="flex-1">Koin &amp; Sinyal</span>
                <span className="w-16 text-right hidden sm:block">24h</span>
                <span className="hidden md:block">RSI</span>
                <span className="w-14 text-right hidden lg:block">Vol</span>
                <span className="hidden xl:block">TF</span>
                <span className="w-4" />
              </div>
              {rest.map((r, i) => (
                <OpportunityRow
                  key={r.symbol}
                  r={r}
                  rank={i + TOP_FEATURED + 1}
                  isNew={newSymbols.has(r.symbol)}
                  onClick={() => setSelectedCoin(r)}
                />
              ))}
            </Card>
          )}
        </>
      )}

      {/* ── Breakout Hunter section ────────────────────────────────────────── */}
      {!loading && filteredBreakout.length > 0 && (
        <div className="space-y-3">
          {/* Section header */}
          <div className="rounded-2xl bg-gradient-to-r from-orange-900/80 via-orange-800/70 to-amber-900/80 border border-orange-700/50 px-5 py-3.5">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xl">🚀</span>
                  <h2 className="text-white font-bold text-base">Breakout Hunter</h2>
                  <span className="text-[10px] bg-orange-500/30 text-orange-200 border border-orange-500/40 px-2 py-0.5 rounded-full font-bold">
                    {filteredBreakout.length} sinyal
                  </span>
                </div>
                <p className="text-orange-200/70 text-[11px] leading-relaxed max-w-lg">
                  Entry <strong className="text-orange-100">SETELAH</strong> breakout dimulai — momentum trade, bukan setup akumulasi.
                  SL lebih ketat (ATR-based), hold max 6 jam, profil risiko berbeda dari lane akumulasi.
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-[10px] text-orange-300/60 bg-orange-900/50 border border-orange-700/40 px-3 py-1.5 rounded-xl flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse" />
                  Vol spike + momentum
                </span>
              </div>
            </div>
          </div>

          {/* Breakout cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {filteredBreakout.slice(0, 8).map((r, i) => (
              <OpportunityFeatured
                key={r.symbol}
                r={r}
                rank={i + 1}
                isNew={newSymbols.has(r.symbol)}
                onClick={() => setSelectedCoin(r)}
              />
            ))}
          </div>
        </div>
      )}

      {/* ── Empty ─────────────────────────────────────────────────────────── */}
      {!loading && filtered.length === 0 && results.length > 0 && filteredBreakout.length === 0 && (
        <div className="text-center py-12 text-neutral-400">
          <p className="text-3xl mb-3">🔍</p>
          <p className="font-semibold">Tidak ada hasil untuk filter ini</p>
          <button
            onClick={() => { setAlert("ALL"); setMinScore(30); setSearch(""); }}
            className="mt-3 text-sm text-teal-600 hover:text-teal-500 underline"
          >
            Reset semua filter
          </button>
        </div>
      )}

      {/* ── No data state ──────────────────────────────────────────────────── */}
      {!loading && results.length === 0 && !scanning && (
        <div className="text-center py-12 text-neutral-400">
          <p className="text-3xl mb-3">📡</p>
          <p className="font-semibold">Belum ada data</p>
          <p className="text-xs mt-1">
            {connState === "connected"
              ? "Scanner sedang menunggu siklus pertama"
              : "Menunggu koneksi..."}
          </p>
        </div>
      )}

      {/* ── Coin detail modal ──────────────────────────────────────────────── */}
      {selectedCoin && (
        <CoinModal r={selectedCoin} onClose={() => setSelectedCoin(null)} />
      )}

    </div>
  );
}
