"use client";
import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { DBHistoryTable } from "@/features/health/components/DBHistoryTable";

import type {
  ApiBalance, OppPosition,
  OppStats, ScanMeta,
} from "./OppSpotTypes";
import { DepositModal }       from "./DepositModal";
import { BalanceBanner }      from "./BalanceBanner";
import { StatsRow }           from "./StatsRow";
import { PnlCalendar, localDayKey } from "./PnlCalendar";
import { LanePerformance, type LaneStat } from "./LanePerformance";
import { OpenPositionsList }  from "./OpenPositionsList";
import { OppSpotToolbar }     from "./OppSpotToolbar";
import { laneFromPosition, LANES, SPOT_LANE_KEYS } from "@/lib/lanes";

const REFRESH_INTERVAL = 15_000;
// Jendela riwayat yang diminta dari API — dipakai juga sebagai label panel lane
// supaya angka win-rate tak pernah terbaca sebagai "sepanjang masa".
const HISTORY_DAYS = 30;

const STATUS_LABEL: Record<string, string> = {
  tp: "TP Hit", sl: "SL Hit", manual: "Ditutup Manual",
};

// ── Main Component ─────────────────────────────────────────────────────────────

export function OppSpotTab() {
  const [positions, setPositions]     = useState<OppPosition[]>([]);
  const [apiBalance, setApiBalance]   = useState<ApiBalance | null>(null);
  const [scanMeta, setScanMeta]       = useState<ScanMeta | null>(null);
  const [loading, setLoading]         = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError]             = useState(false);
  const [closingId, setClosingId]     = useState<number | null>(null);
  const [countdown, setCountdown]     = useState(REFRESH_INTERVAL / 1000);
  const [showDeposit, setShowDeposit] = useState(false);
  const [depositAmt, setDepositAmt]   = useState("");
  const [depositing, setDepositing]   = useState(false);

  const countRef      = useRef(REFRESH_INTERVAL / 1000);
  const prevStatusRef = useRef<Map<number, string>>(new Map());

  // ── Fetch helpers ──────────────────────────────────────────────────────────

  const fetchBalance = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/balance/spot");
      if (r.ok) setApiBalance(await r.json() as ApiBalance);
    } catch { /* silent */ }
  }, []);

  // S2: corong per lane + status regime dari cache scan (read-only, tak memicu scan).
  // limit=1 karena kita hanya butuh metadatanya, bukan daftar hasilnya.
  const fetchScanMeta = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/opportunity/scan?min_score=0&limit=1");
      if (r.ok) setScanMeta(await r.json() as ScanMeta);
    } catch { /* silent — panel lane tetap tampil tanpa corong */ }
  }, []);

  const fetchPositions = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(false);
    try {
      const r = await fetch(`/api/v1/opportunity/positions?days=${HISTORY_DAYS}`);
      if (!r.ok) { setError(true); return; }
      const d = await r.json() as { positions: OppPosition[]; total: number };
      const next = d.positions ?? [];

      if ("Notification" in window && Notification.permission === "granted") {
        next.forEach(p => {
          const prev = prevStatusRef.current.get(p.id);
          if (prev === "open" && p.status !== "open") {
            const pnlStr = p.pnl_pct != null
              ? `${p.pnl_pct >= 0 ? "+" : ""}${p.pnl_pct.toFixed(2)}%`
              : "";
            const icon = p.status === "tp" ? "✅" : p.status === "sl" ? "🛑" : "🤚";
            new Notification(`${icon} ${p.symbol.replace("USDT", "")} Tertutup`, {
              body: `${STATUS_LABEL[p.status] ?? p.status}${pnlStr ? " · " + pnlStr : ""}`,
              tag:  `opp-${p.id}`,
            });
          }
        });
      }
      // §8.7: prune ref untuk trade yang sudah tidak ada di respons
      const liveIds = new Set(next.map(p => p.id));
      prevStatusRef.current.forEach((_, id) => {
        if (!liveIds.has(id)) prevStatusRef.current.delete(id);
      });
      next.forEach(p => prevStatusRef.current.set(p.id, p.status));
      setPositions(next);
      setLastUpdated(new Date());
    } catch {
      setError(true);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  // ── Actions ────────────────────────────────────────────────────────────────

  const handleDeposit = useCallback(async () => {
    const amt = parseFloat(depositAmt);
    if (!amt || amt <= 0) return;
    setDepositing(true);
    try {
      const r = await fetch("/api/v1/balance/spot/deposit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: amt, notes: "Manual deposit via UI" }),
      });
      if (r.ok) {
        const d = await r.json() as { balance: number; message: string };
        setApiBalance(prev =>
          prev
            ? { ...prev, balance: d.balance, available: d.balance - (prev.locked_margin ?? 0) }
            : prev
        );
        setShowDeposit(false);
        setDepositAmt("");
        await fetchBalance();
      } else {
        alert("Deposit gagal");
      }
    } catch { alert("Deposit gagal"); }
    finally { setDepositing(false); }
  }, [depositAmt, fetchBalance]);

  const closePosition = useCallback(async (id: number, symbol: string) => {
    if (!confirm(`Tutup posisi ${symbol.replace("USDT", "")}/USDT sekarang di harga pasar?`)) return;
    setClosingId(id);
    try {
      const r = await fetch(`/api/v1/opportunity/positions/${id}/close`, { method: "POST" });
      if (!r.ok) { alert("Gagal menutup posisi"); return; }
      await fetchPositions(true);
    } catch { alert("Gagal menutup posisi"); }
    finally { setClosingId(null); }
  }, [fetchPositions]);

  const requestNotifPermission = useCallback(async () => {
    if (!("Notification" in window)) return;
    await Notification.requestPermission();
  }, []);

  const exportCSV = useCallback(() => {
    // S6: kolom "Lane" kini dari identitas immutable. "Mode Saat Tutup" diberi
    // nama apa adanya — ia state akhir monitor, BUKAN mode saat entry.
    const headers = [
      "ID","Symbol","Status","Lane","Mode Saat Tutup","Alert Type","Manual","Entry","SL","TP1","TP2",
      "Close Price","P&L %","Score","R:R","Entry Date","Close Date",
    ];
    const rows = positions.map(p => [
      p.id, p.symbol, p.status,
      laneFromPosition(p).label,                         // PLAN_v9 G1c + S6
      p.entry_mode ?? "",
      p.alert_type, p.manual ? "yes" : "",
      p.entry, p.sl, p.tp1 ?? "", p.tp2,
      p.close_price ?? "", p.pnl_pct ?? "",
      p.score, p.rr_ratio,
      p.entry_at  ? new Date(p.entry_at  * 1000).toLocaleString("id-ID") : "",
      p.closed_at ? new Date(p.closed_at * 1000).toLocaleString("id-ID") : "",
    ]);
    const csv  = [headers, ...rows].map(r => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `opportunity_spot_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [positions]);

  // ── Effects ────────────────────────────────────────────────────────────────

  useEffect(() => {
    void fetchPositions();
    void fetchBalance();
    void fetchScanMeta();
  }, [fetchPositions, fetchBalance, fetchScanMeta]);

  useEffect(() => {
    const poll = setInterval(() => {
      void fetchPositions(true);
      void fetchBalance();
      void fetchScanMeta();
      countRef.current = REFRESH_INTERVAL / 1000;
      setCountdown(REFRESH_INTERVAL / 1000);
    }, REFRESH_INTERVAL);
    const tick = setInterval(() => {
      countRef.current = Math.max(0, countRef.current - 1);
      setCountdown(countRef.current);
    }, 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [fetchPositions, fetchBalance, fetchScanMeta]);

  // ── Derived stats ──────────────────────────────────────────────────────────

  const stats = useMemo((): OppStats => {
    const open   = positions.filter(p => p.status === "open");
    const tp     = positions.filter(p => p.status === "tp");
    const sl     = positions.filter(p => p.status === "sl");
    const manual = positions.filter(p => p.status === "manual");
    const wins   = tp.filter(p => (p.pnl_pct ?? 0) > 0);

    const expired = positions.filter(p => p.status === "expired");
    const winRate = (tp.length + sl.length + expired.length) > 0
      ? (wins.length / (tp.length + sl.length + expired.length)) * 100
      : 0;
    const allClosed  = [...tp, ...sl, ...manual];
    const avgPnl     = allClosed.length > 0
      ? allClosed.reduce((s, p) => s + (p.pnl_pct ?? 0), 0) / allClosed.length
      : 0;
    const autoOpened = positions.filter(p => p.auto_open).length;

    const initialBalance = apiBalance?.initial_balance ?? 1000;
    const riskDollar     = initialBalance * 0.01;

    let runningBalance = initialBalance;
    const equityPoints = [{ n: 0, balance: runningBalance, win: true, symbol: "" }];
    const sortedClosed = [...allClosed].sort((a, b) => (a.closed_at ?? 0) - (b.closed_at ?? 0));

    sortedClosed.forEach((p, i) => {
      const pnl$ = p.pnl_dollar ?? (() => {
        const rp       = p.risk_pct > 0 ? p.risk_pct : 2.0;
        const notional = riskDollar / (rp / 100);
        return ((p.pnl_pct ?? 0) / 100) * notional;
      })();
      runningBalance = Math.max(0, runningBalance + pnl$);
      equityPoints.push({
        n: i + 1, balance: runningBalance,
        win: (p.pnl_pct ?? 0) >= 0, symbol: p.symbol.replace("USDT", ""),
      });
    });

    // §8.1: kunci kalender pakai hari LOKAL (WIB), bukan UTC
    const calendarMap = new Map<string, number>();
    sortedClosed.forEach(p => {
      if (!p.closed_at) return;
      const day  = localDayKey(new Date(p.closed_at * 1000));
      const pnl$ = p.pnl_dollar ?? (() => {
        const rp       = p.risk_pct > 0 ? p.risk_pct : 2.0;
        const notional = riskDollar / (rp / 100);
        return ((p.pnl_pct ?? 0) / 100) * notional;
      })();
      calendarMap.set(day, (calendarMap.get(day) ?? 0) + pnl$);
    });

    const currentBalance    = apiBalance?.balance ?? runningBalance;
    const availableBalance$ = apiBalance?.available
      ?? (currentBalance - (apiBalance?.locked_margin ?? 0));
    const totalNotional$    = apiBalance?.locked_margin ?? open.reduce((s, p) => {
      const rp = p.risk_pct > 0 ? p.risk_pct : 2.0;
      return s + (riskDollar / (rp / 100));
    }, 0);
    const avgNotional$  = open.length > 0 ? totalNotional$ / open.length : riskDollar / 0.02;
    const maxConcurrent = Math.floor(currentBalance / (avgNotional$ || 1));

    return {
      total: positions.length, open: open.length,
      tp: tp.length, sl: sl.length, manual: manual.length,
      wins: wins.length, winRate, avgPnl, autoOpened,
      currentBalance,
      totalPnl$: apiBalance?.realized_pnl ?? (currentBalance - initialBalance),
      // §9.6: render maksimal 100 titik equity terakhir
      equityPoints: equityPoints.slice(-100),
      calendarMap,
      totalRisk$:       open.reduce((s, p) => s + (p.risk_dollar ?? riskDollar), 0),
      totalNotional$, availableBalance$, maxConcurrent,
      initialBalance, riskDollar,
    };
  }, [positions, apiBalance]);

  const closedList = useMemo(
    () => positions.filter(p => p.status !== "open"),
    [positions]
  );

  // PLAN_v9 G1a — performa per LANE, dinamis dari data aktual (semua lane yang
  // benar-benar muncul, termasuk BigMover & Early Radar yang dulu invisible).
  // Semua lane SPOT yang di-scan agent selalu tampil — lane tanpa trade dulu
  // hilang diam-diam, sehingga tampak "cuma ada 3 lane".
  const laneStats = useMemo((): LaneStat[] => {
    const map = new Map<string, { label: string; emoji: string; total: number; wins: number; sumPnl: number; pnl$: number; open: number }>();
    const seed = (key: string) => {
      const info = LANES[key];
      const cur  = map.get(key) ?? {
        label: info?.label ?? key, emoji: info?.emoji ?? "🎯",
        total: 0, wins: 0, sumPnl: 0, pnl$: 0, open: 0,
      };
      map.set(key, cur);
      return cur;
    };
    SPOT_LANE_KEYS.forEach(seed);

    positions.forEach(p => {
      // S6: pakai lane immutable dari backend; laneForSpot hanya cadangan untuk
      // respons lama. Jangan mengelompokkan lewat entry_mode — nilainya ditulis
      // ulang monitor jadi "momentum_chase" begitu TP2 tersentuh, sehingga
      // pengelompokan per mode selalu condong ke arah pemenang.
      const lane = laneFromPosition(p);
      const cur  = seed(lane.key);
      cur.label  = lane.label;
      cur.emoji  = lane.emoji;
      if (p.status === "open") { cur.open += 1; return; }
      if (p.status !== "tp" && p.status !== "sl") return;
      cur.total  += 1;
      cur.wins   += p.status === "tp" && (p.pnl_pct ?? 0) > 0 ? 1 : 0;
      cur.sumPnl += p.pnl_pct ?? 0;
      cur.pnl$   += p.pnl_dollar ?? 0;
    });

    return [...map.entries()]
      .map(([key, v]) => ({
        key, label: v.label, emoji: v.emoji, total: v.total, wins: v.wins,
        winRate: v.total > 0 ? v.wins / v.total * 100 : 0,
        avgPnl:  v.total > 0 ? v.sumPnl / v.total : 0,
        pnl$:    v.pnl$,
        open:    v.open,
      }))
      .sort((a, b) => b.total - a.total || b.open - a.open);
  }, [positions]);

  const openList = useMemo(() => positions.filter(p => p.status === "open"), [positions]);

  const notifPermission = typeof window !== "undefined" && "Notification" in window
    ? Notification.permission
    : "default";

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading && positions.length === 0) {
    return (
      <div className="text-center py-16 text-neutral-400">
        <div className="w-10 h-10 border-2 border-teal-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p>Memuat posisi...</p>
      </div>
    );
  }
  if (error && positions.length === 0) {
    return (
      <div className="text-center py-16">
        <p className="text-3xl mb-2">⚠️</p>
        <p className="font-semibold text-neutral-600">Gagal memuat posisi</p>
        <button
          onClick={() => void fetchPositions()}
          className="mt-3 text-sm text-teal-600 underline"
        >
          Coba lagi
        </button>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">

      <DepositModal
        show={showDeposit}
        depositAmt={depositAmt}
        depositing={depositing}
        currentBalance={apiBalance?.balance ?? 0}
        onClose={() => { setShowDeposit(false); setDepositAmt(""); }}
        onAmtChange={setDepositAmt}
        onDeposit={() => void handleDeposit()}
      />

      <BalanceBanner
        stats={stats}
        apiBalance={apiBalance}
        openCount={openList.length}
        onDeposit={() => setShowDeposit(true)}
      />

      <StatsRow stats={stats} />

      <PnlCalendar
        calendarMap={stats.calendarMap}
        closedTrades={closedList}
        balance={stats.currentBalance}
      />

      <LanePerformance laneStats={laneStats} windowDays={HISTORY_DAYS} scanMeta={scanMeta} />

      <OppSpotToolbar
        positionCount={positions.length}
        loading={loading}
        countdown={countdown}
        lastUpdated={lastUpdated}
        notifPermission={notifPermission}
        onExport={exportCSV}
        onRefresh={() => void fetchPositions()}
        onRequestNotif={() => void requestNotifPermission()}
      />

      <OpenPositionsList
        openList={openList}
        stats={stats}
        closingId={closingId}
        onClose={closePosition}
      />

      {/* Empty state */}
      {positions.length === 0 && !loading && (
        <div className="text-center py-16 text-neutral-400">
          <p className="text-4xl mb-3">🎯</p>
          <p className="font-semibold text-neutral-600">Belum ada posisi Opportunity SPOT</p>
          <p className="text-sm mt-2 max-w-sm mx-auto">
            Buka halaman <strong>Opportunity</strong>, klik koin, lalu{" "}
            <strong className="text-teal-600">Buka Posisi SPOT</strong>
          </p>
        </div>
      )}

      {/* DB History Table */}
      <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-neutral-100 bg-neutral-50">
          <h3 className="font-bold text-sm text-neutral-700">
            🗄 Riwayat Database — Spot Opportunity
          </h3>
          <p className="text-[10px] text-neutral-400 mt-0.5">
            Semua trade · pencarian · pagination · alasan tutup posisi
          </p>
        </div>
        <div className="p-4">
          <DBHistoryTable
            defaultStyle="spot"
            hideStyleTabs={true}
            compact={true}
            autoRefresh={15000}
            reasonScope="spot"
          />
        </div>
      </div>

    </div>
  );
}
