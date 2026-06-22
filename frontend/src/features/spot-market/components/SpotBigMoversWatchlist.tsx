"use client";
import { useCallback, useEffect, useMemo, useState } from "react";

// Phase 1 T2 — Big Movers Watchlist di Spot Market page.
// Force-open enabled only for vol > $1M (mengikuti spec plan).
// Backed by /market/spot-overview.big_movers + /opportunity/trade + force-open budget.

interface SpotMover {
  symbol: string;
  base: string;
  last_price: number;
  change_pct: number;
  quote_vol_24h: number;
}

interface ForceOpenBudget {
  used: number;
  remaining: number;
  limit: number;
}

const MIN_FORCE_VOL = 1_000_000;       // plan: $1M
const RISK_PCT = 2.0;
const SL_PCT = 4.0;
const TP1_PCT = 6.0;
const TP2_PCT = 12.0;
const TP3_PCT = 20.0;

function sessionId(): string {
  if (typeof window === "undefined") return "default";
  let s = window.localStorage.getItem("force_open_session");
  if (!s) {
    s = `s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    window.localStorage.setItem("force_open_session", s);
  }
  return s;
}

export function SpotBigMoversWatchlist({ movers }: { movers: SpotMover[] }) {
  const [budget, setBudget] = useState<ForceOpenBudget | null>(null);
  const [selected, setSelected] = useState<SpotMover | null>(null);
  const [open, setOpen] = useState(false);
  const sid = useMemo(() => sessionId(), []);

  const refreshBudget = useCallback(async () => {
    try {
      const r = await fetch(`/api/v1/futures/force-open/budget?session_id=${sid}`);
      if (r.ok) setBudget((await r.json()) as ForceOpenBudget);
    } catch {
      /* silent */
    }
  }, [sid]);

  useEffect(() => {
    void refreshBudget();
    const t = setInterval(() => void refreshBudget(), 30_000);
    return () => clearInterval(t);
  }, [refreshBudget]);

  // Filter LONG-only candidates (spot is LONG-only), volume gated
  const gainers = movers
    .filter((m) => m.change_pct > 0)
    .sort((a, b) => b.change_pct - a.change_pct);
  if (gainers.length === 0) return null;

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-4 py-3 hover:bg-neutral-50"
      >
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-bold text-neutral-700">⚡ Spot Big Movers Watchlist</span>
          <span className="text-[10px] bg-neutral-100 text-neutral-500 px-2 py-0.5 rounded-full font-semibold">
            {gainers.length} gainers
          </span>
          {budget && (
            <span className="text-[10px] bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold">
              Force-open: {budget.remaining}/{budget.limit}
            </span>
          )}
        </div>
        <span className={`text-neutral-400 transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
      </button>

      {open && (
        <div className="border-t border-neutral-100 px-4 py-3 space-y-2 max-h-[480px] overflow-y-auto">
          <p className="text-[10px] text-neutral-400">
            Force-open spot dengan {RISK_PCT}% risk. SL {SL_PCT}% · TP2 {TP2_PCT}% (1:3 R:R). Min volume $1M.
          </p>
          {gainers.slice(0, 30).map((m) => {
            const lowVol = m.quote_vol_24h < MIN_FORCE_VOL;
            return (
              <div
                key={m.symbol}
                className="flex items-center gap-2 text-xs border rounded-lg px-3 py-1.5 bg-neutral-50 border-neutral-100"
              >
                <span className="font-bold w-20 shrink-0">{m.base}</span>
                <span
                  className={`font-mono font-semibold w-16 shrink-0 ${
                    m.change_pct >= 0 ? "text-green-600" : "text-red-500"
                  }`}
                >
                  {m.change_pct >= 0 ? "+" : ""}
                  {m.change_pct.toFixed(1)}%
                </span>
                <span className="text-[10px] text-neutral-500 flex-1 min-w-0 truncate">
                  Vol ${(m.quote_vol_24h / 1e6).toFixed(2)}M · Price ${m.last_price.toFixed(4)}
                </span>
                <button
                  onClick={() => setSelected(m)}
                  disabled={lowVol}
                  title={lowVol ? `Volume di bawah $${MIN_FORCE_VOL.toLocaleString()}` : ""}
                  className="text-[10px] font-bold px-2 py-1 rounded bg-amber-100 hover:bg-amber-200 text-amber-800 shrink-0 disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Force-Open
                </button>
              </div>
            );
          })}
        </div>
      )}

      {selected && (
        <ForceOpenModal
          mover={selected}
          sessionId={sid}
          onClose={() => setSelected(null)}
          onOpened={() => {
            setSelected(null);
            void refreshBudget();
          }}
        />
      )}
    </div>
  );
}

function ForceOpenModal({
  mover,
  sessionId: sid,
  onClose,
  onOpened,
}: {
  mover: SpotMover;
  sessionId: string;
  onClose: () => void;
  onOpened: () => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setSubmitting(true);
    setError("");
    try {
      const entry = mover.last_price;
      const sl = entry * (1 - SL_PCT / 100);
      const tp1 = entry * (1 + TP1_PCT / 100);
      const tp2 = entry * (1 + TP2_PCT / 100);
      const tp3 = entry * (1 + TP3_PCT / 100);

      const body = {
        symbol: mover.symbol,
        entry,
        sl,
        tp1,
        tp2,
        tp3,
        risk_pct: RISK_PCT,
        tp1_pct: TP1_PCT,
        tp2_pct: TP2_PCT,
        tp3_pct: TP3_PCT,
        rr_ratio: TP2_PCT / SL_PCT,
        opportunity_score: 0,
        alert_type: "manual_bigmover",
        signals: [`Manual force-open · spot big-mover +${mover.change_pct.toFixed(1)}%`],
        taker_ratio: 0.5,
        confidence: 50,
        entry_mode: "manual",
        force_open: true,
        session_id: sid,
      };
      const res = await fetch("/api/v1/opportunity/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const e = (await res.json()) as { detail?: string };
        throw new Error(e.detail ?? `HTTP ${res.status}`);
      }
      onOpened();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const extremeMove = mover.change_pct > 50;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl max-w-md w-full overflow-hidden shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-neutral-100 flex items-center gap-2">
          <span className="text-base font-black">⚠ Force-Open Spot</span>
          <span className="ml-auto text-xs text-neutral-400">{mover.symbol}</span>
        </div>
        <div className="p-5 space-y-3 text-sm">
          {extremeMove && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-700 font-semibold">
              Δ24h +{mover.change_pct.toFixed(1)}% — extreme parabolic. Reversal risk tinggi.
            </div>
          )}

          <div className="bg-neutral-50 border border-neutral-200 rounded-lg p-3 text-xs space-y-1.5">
            <div className="flex justify-between">
              <span className="text-neutral-500">Δ24h</span>
              <span className="font-bold text-green-600">+{mover.change_pct.toFixed(2)}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">Entry (live)</span>
              <span className="font-mono">${mover.last_price.toFixed(6)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-neutral-500">Volume 24h</span>
              <span>${(mover.quote_vol_24h / 1e6).toFixed(2)}M</span>
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-[11px] text-blue-700 leading-snug">
            <strong>Slippage warning:</strong> spot taker fee 0.1% × 2 sisi. Untuk coin pump
            +{mover.change_pct.toFixed(0)}%, slippage entry market biasa 0.3–0.7%. SL {SL_PCT}% ·
            TP2 {TP2_PCT}% · R:R 1:{(TP2_PCT / SL_PCT).toFixed(1)} · Risk {RISK_PCT}% wallet.
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-2 text-xs text-red-700">
              {error}
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button
              onClick={onClose}
              disabled={submitting}
              className="flex-1 py-2 rounded-lg text-sm font-semibold bg-neutral-100 hover:bg-neutral-200 text-neutral-600 disabled:opacity-50"
            >
              Batal
            </button>
            <button
              onClick={submit}
              disabled={submitting}
              className="flex-1 py-2 rounded-lg text-sm font-bold bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50"
            >
              {submitting ? "Membuka..." : "Force LONG"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
