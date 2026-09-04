"use client";
import { apiFetch } from "@/lib/api";
import { useCallback, useEffect, useMemo, useState } from "react";

// Phase 1 T1 — Big Movers Watchlist di Futures Overview.
// User visibility + manual override (force-open). Backed by /futures/big-movers
// + /futures/eligibility + /futures/force-open/budget.

interface BigMoverMatch {
  agent: string;
  direction: "LONG" | "SHORT";
  score: number;
}
interface BigMover {
  symbol: string;
  change_24h: number;
  price?: number;
  funding_rate?: number;
  status: "lolos" | "tidak_lolos";
  reason: string;
  matches: BigMoverMatch[];
}
interface Eligibility {
  symbol: string;
  futures_perpetual: boolean;
  in_universe: boolean;
  matched_score?: number | null;
  scoring_max_achievable?: number | null;
  scoring_threshold?: number | null;
  scoring_gap?: number | null;
  regime_gate: string;
  cooldown_until?: number | null;
  funding_rate?: number | null;
  change_24h?: number | null;
  actionable_reason: string;
}
interface ForceOpenBudget {
  used: number;
  remaining: number;
  limit: number;
}

const AGENT_LABEL: Record<string, string> = {
  futures_agent1: "Pre-Gainer",
  futures_agent2: "Accumulation",
  futures_agent3: "Momentum",
  futures_agent_bigmover: "Big Mover",
};

function sessionId(): string {
  if (typeof window === "undefined") return "default";
  let s = window.localStorage.getItem("force_open_session");
  if (!s) {
    s = `s_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    window.localStorage.setItem("force_open_session", s);
  }
  return s;
}

export function BigMoversWatchlist({ onChanged }: { onChanged?: () => void }) {
  const [movers, setMovers] = useState<BigMover[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(true);
  const [budget, setBudget] = useState<ForceOpenBudget | null>(null);
  const [selected, setSelected] = useState<BigMover | null>(null);
  const sid = useMemo(() => sessionId(), []);

  const refresh = useCallback(async () => {
    try {
      const [m, b] = await Promise.all([
        apiFetch("/api/v1/futures/big-movers?limit=60"),
        apiFetch(`/api/v1/futures/force-open/budget?session_id=${sid}`),
      ]);
      if (m.ok) {
        const d = (await m.json()) as { movers: BigMover[] };
        setMovers(d.movers ?? []);
      }
      if (b.ok) setBudget((await b.json()) as ForceOpenBudget);
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [sid]);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 60_000);
    return () => clearInterval(t);
  }, [refresh]);

  if (loading && movers.length === 0) return null;
  if (movers.length === 0) return null;

  const lolos = movers.filter((m) => m.status === "lolos");
  const tidakLolos = movers.filter((m) => m.status === "tidak_lolos");

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-4 py-3 hover:bg-neutral-50 transition-colors"
      >
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-bold text-neutral-700">📡 Big Movers Watchlist</span>
          <span className="text-[10px] bg-neutral-100 text-neutral-500 px-2 py-0.5 rounded-full font-semibold">
            {movers.length} koin ≥10% 24h
          </span>
          {lolos.length > 0 && (
            <span className="text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-semibold">
              {lolos.length} lolos
            </span>
          )}
          {budget && (
            <span className="text-[10px] bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold">
              Force-open: {budget.remaining}/{budget.limit} sisa
            </span>
          )}
        </div>
        <span className={`text-neutral-400 transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
      </button>

      {open && (
        <div className="border-t border-neutral-100 px-4 py-3 space-y-3 max-h-[480px] overflow-y-auto">
          <p className="text-[10px] text-neutral-400">
            Tab Force-Open membuka posisi futures dengan 1% risk. Wajib R:R ≥ 1:3; rate limit 5/jam (B1.2).
          </p>

          {lolos.length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-green-600 uppercase tracking-wider mb-1.5">
                ✅ Lolos Scoring
              </p>
              <div className="space-y-1">
                {lolos.map((m) => (
                  <MoverRow key={m.symbol} m={m} onForce={() => setSelected(m)} />
                ))}
              </div>
            </div>
          )}

          {tidakLolos.length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider mb-1.5">
                ⏸ Belum Lolos
              </p>
              <div className="space-y-1">
                {tidakLolos.map((m) => (
                  <MoverRow key={m.symbol} m={m} onForce={() => setSelected(m)} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {selected && (
        <ForceOpenModal
          mover={selected}
          sessionId={sid}
          onClose={() => setSelected(null)}
          onOpened={() => {
            setSelected(null);
            void refresh();
            onChanged?.();
          }}
        />
      )}
    </div>
  );
}

function MoverRow({ m, onForce }: { m: BigMover; onForce: () => void }) {
  const tone =
    m.status === "lolos"
      ? "bg-green-50 border-green-100"
      : "bg-neutral-50 border-neutral-100";
  const fr = m.funding_rate;            // raw funding (e.g. 0.0001 = 0.01%)
  const frPct = fr != null ? fr * 100 : null;
  const frTone =
    frPct == null
      ? "text-neutral-400"
      : Math.abs(frPct) > 0.12
        ? "text-red-600 font-bold"
        : Math.abs(frPct) > 0.05
          ? "text-amber-600"
          : "text-neutral-500";
  return (
    <div className={`flex items-center gap-2 text-xs border rounded-lg px-3 py-1.5 ${tone}`}>
      <span className="font-bold w-20 shrink-0">{m.symbol.replace("USDT", "")}</span>
      <span
        className={`font-mono font-semibold w-16 shrink-0 ${
          m.change_24h >= 0 ? "text-green-600" : "text-red-500"
        }`}
      >
        {m.change_24h >= 0 ? "+" : ""}
        {m.change_24h.toFixed(1)}%
      </span>
      <span
        title="Funding rate (8h) — extreme = bayar mahal"
        className={`text-[10px] font-mono w-16 shrink-0 ${frTone}`}
      >
        {frPct == null ? "—" : `${frPct >= 0 ? "+" : ""}${frPct.toFixed(3)}%`}
      </span>
      {m.matches.length > 0 ? (
        <div className="flex gap-1 flex-wrap flex-1">
          {m.matches.map((mt, i) => (
            <span
              key={i}
              className="text-[9px] bg-white border border-green-200 text-green-700 px-1.5 py-0.5 rounded font-semibold"
            >
              {AGENT_LABEL[mt.agent] ?? mt.agent} {mt.direction} · {mt.score}pt
            </span>
          ))}
        </div>
      ) : (
        <span className="text-[10px] text-neutral-400 flex-1 min-w-0 truncate">{m.reason}</span>
      )}
      <button
        onClick={onForce}
        className="text-[10px] font-bold px-2 py-1 rounded bg-amber-100 hover:bg-amber-200 text-amber-800 shrink-0 transition-colors"
      >
        Force-Open
      </button>
    </div>
  );
}

function ForceOpenModal({
  mover,
  sessionId: sid,
  onClose,
  onOpened,
}: {
  mover: BigMover;
  sessionId: string;
  onClose: () => void;
  onOpened: () => void;
}) {
  const [direction, setDirection] = useState<"LONG" | "SHORT">(mover.change_24h >= 0 ? "LONG" : "SHORT");
  const [elig, setElig] = useState<Eligibility | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const r = await apiFetch(`/api/v1/futures/eligibility/${mover.symbol}`);
        if (r.ok && alive) setElig((await r.json()) as Eligibility);
      } catch {
        /* silent */
      }
    })();
    return () => {
      alive = false;
    };
  }, [mover.symbol]);

  const noPerp = elig?.futures_perpetual === false;
  const extremeFunding =
    elig?.funding_rate != null && Math.abs(elig.funding_rate * 100) > 0.12;

  const submit = async () => {
    setSubmitting(true);
    setError("");
    try {
      const livePrice = mover.price ?? 0;
      if (livePrice <= 0) {
        throw new Error("Harga koin tidak tersedia di cache scanner — tunggu cycle berikutnya.");
      }

      // 4% SL, 12% TP1, 1:3 RR via TP2 — manual force entry
      const slPct = 0.04;
      const tp1Pct = 0.06;
      const tp2Pct = 0.12;
      const tp3Pct = 0.2;
      const sl =
        direction === "LONG"
          ? livePrice * (1 - slPct)
          : livePrice * (1 + slPct);
      const tp1 =
        direction === "LONG" ? livePrice * (1 + tp1Pct) : livePrice * (1 - tp1Pct);
      const tp2 =
        direction === "LONG" ? livePrice * (1 + tp2Pct) : livePrice * (1 - tp2Pct);
      const tp3 =
        direction === "LONG" ? livePrice * (1 + tp3Pct) : livePrice * (1 - tp3Pct);

      const body = {
        symbol: mover.symbol,
        direction,
        agent: "futures_agent_bigmover",
        entry: livePrice,
        sl,
        tp1,
        tp2,
        tp3,
        risk_pct: slPct * 100,
        tp1_pct: tp1Pct * 100,
        tp2_pct: tp2Pct * 100,
        tp3_pct: tp3Pct * 100,
        rr_ratio: tp2Pct / slPct,
        leverage: 3,
        score: elig?.matched_score ?? 0,
        signals: [`Manual force-open · ${mover.reason}`],
        funding_rate: elig?.funding_rate ?? 0,
        force_open: true,
        session_id: sid,
      };
      const res = await apiFetch("/api/v1/futures/trade", {
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
          <span className="text-base font-black">⚠ Force-Open Posisi</span>
          <span className="ml-auto text-xs text-neutral-400">{mover.symbol}</span>
        </div>
        <div className="p-5 space-y-3 text-sm">
          {noPerp && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700 font-semibold">
              {mover.symbol} tidak punya futures perpetual — tidak bisa di-open dari sini.
            </div>
          )}
          {extremeFunding && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-700">
              Funding rate {((elig?.funding_rate ?? 0) * 100).toFixed(3)}% — extreme. Posisi {direction} akan
              bayar funding mahal per 8 jam.
            </div>
          )}

          <div className="bg-neutral-50 border border-neutral-200 rounded-lg p-3 text-xs space-y-1.5">
            <div className="flex justify-between">
              <span className="text-neutral-500">Δ24h</span>
              <span
                className={`font-bold ${
                  mover.change_24h >= 0 ? "text-green-600" : "text-red-500"
                }`}
              >
                {mover.change_24h >= 0 ? "+" : ""}
                {mover.change_24h.toFixed(2)}%
              </span>
            </div>
            {elig?.scoring_max_achievable != null && (
              <div className="flex justify-between">
                <span className="text-neutral-500">Max score</span>
                <span>
                  {elig.scoring_max_achievable} / threshold {elig.scoring_threshold}
                </span>
              </div>
            )}
            {elig?.actionable_reason && (
              <p className="text-[11px] text-neutral-500 pt-1 leading-snug">
                {elig.actionable_reason}
              </p>
            )}
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-[11px] text-blue-700 leading-snug">
            <strong>Slippage warning:</strong> entry market-order pada coin ber-volatilitas tinggi
            biasanya kena slippage 0.3–0.7%. Risk per trade = 1% wallet. SL 4% · TP2 12% · R:R 1:3.
          </div>

          <div className="flex gap-2">
            {(["LONG", "SHORT"] as const).map((d) => (
              <button
                key={d}
                onClick={() => setDirection(d)}
                disabled={noPerp}
                className={`flex-1 py-2 rounded-lg text-sm font-bold border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                  direction === d
                    ? d === "LONG"
                      ? "bg-green-100 border-green-300 text-green-800"
                      : "bg-red-100 border-red-300 text-red-800"
                    : "bg-white border-neutral-200 text-neutral-500 hover:border-neutral-300"
                }`}
              >
                {d}
              </button>
            ))}
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
              disabled={noPerp || submitting}
              className="flex-1 py-2 rounded-lg text-sm font-bold bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? "Membuka..." : `Force ${direction}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
