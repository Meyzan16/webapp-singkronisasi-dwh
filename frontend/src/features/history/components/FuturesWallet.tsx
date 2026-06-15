"use client";
import { useCallback, useEffect, useState } from "react";

// Phase 9: one futures wallet — deposit/withdraw + an auditable balance-sheet statement.

interface WalletInfo {
  balance:        number;
  available:      number;
  locked_margin:  number;
  open_positions: number;
}

interface StatementEvent {
  ts:            number;
  kind:          string;   // deposit | withdraw | reset | trade
  amount:        number;
  label:         string;
  balance_after: number;
}

const KIND_META: Record<string, { icon: string; cls: string }> = {
  deposit:  { icon: "⬇", cls: "text-green-600" },
  withdraw: { icon: "⬆", cls: "text-red-500" },
  reset:    { icon: "↺", cls: "text-neutral-500" },
  trade:    { icon: "•", cls: "text-neutral-700" },
};

export function FuturesWallet({ onChanged }: { onChanged?: () => void }) {
  const [info,    setInfo]    = useState<WalletInfo | null>(null);
  const [events,  setEvents]  = useState<StatementEvent[]>([]);
  const [mode,    setMode]    = useState<null | "deposit" | "withdraw">(null);
  const [amt,     setAmt]     = useState("");
  const [busy,    setBusy]    = useState(false);
  const [err,     setErr]     = useState("");
  const [showAll, setShowAll] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [bRes, sRes] = await Promise.all([
        fetch("/api/v1/balance/futures"),
        fetch("/api/v1/balance/futures/statement?limit=100"),
      ]);
      if (bRes.ok) setInfo(await bRes.json() as WalletInfo);
      if (sRes.ok) {
        const d = await sRes.json() as { events: StatementEvent[] };
        setEvents(d.events ?? []);
      }
    } catch { /* silent */ }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const submit = useCallback(async () => {
    const value = parseFloat(amt);
    if (!value || value <= 0) return;
    setBusy(true); setErr("");
    try {
      const ep = mode === "withdraw" ? "withdraw" : "deposit";
      const r = await fetch(`/api/v1/balance/futures/${ep}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: value }),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => ({})) as { detail?: string };
        throw new Error(e.detail ?? "Gagal");
      }
      setMode(null); setAmt("");
      await refresh();
      onChanged?.();
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }, [amt, mode, refresh, onChanged]);

  const shown = showAll ? events : events.slice(0, 6);

  return (
    <div className="bg-white border border-neutral-200 rounded-2xl p-4">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <div>
          <p className="text-xs font-bold text-neutral-500 uppercase tracking-wider">💼 Dompet Futures</p>
          <p className="text-[10px] text-neutral-400 mt-0.5">Satu wallet cross-margin · 1 Scanner (semua strategi) · deposit lalu agen bekerja</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => { setMode("deposit"); setAmt(""); setErr(""); }}
            className="text-xs bg-teal-600 hover:bg-teal-500 text-white font-semibold px-3 py-1.5 rounded-lg">
            + Deposit
          </button>
          <button onClick={() => { setMode("withdraw"); setAmt(""); setErr(""); }}
            className="text-xs bg-white border border-neutral-300 hover:bg-neutral-50 text-neutral-700 font-semibold px-3 py-1.5 rounded-lg">
            − Withdraw
          </button>
        </div>
      </div>

      {/* Balance summary */}
      {info && (
        <div className="grid grid-cols-3 gap-2 mb-3 text-center">
          {[
            { label: "Saldo",     value: info.balance,       cls: "text-neutral-900" },
            { label: "Bebas",     value: info.available,     cls: "text-green-600" },
            { label: "Terkunci",  value: info.locked_margin, cls: "text-orange-600" },
          ].map(x => (
            <div key={x.label} className="bg-neutral-50 rounded-xl p-2">
              <p className={`text-lg font-black tabular-nums ${x.cls}`}>${x.value.toFixed(2)}</p>
              <p className="text-[9px] text-neutral-400">{x.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Statement / balance sheet */}
      {events.length > 0 ? (
        <div className="border border-neutral-100 rounded-xl overflow-hidden">
          <div className="px-3 py-1.5 bg-neutral-50 border-b border-neutral-100 flex justify-between">
            <span className="text-[10px] font-bold text-neutral-500 uppercase tracking-wider">Riwayat Saldo</span>
            <span className="text-[10px] text-neutral-400">{events.length} entri</span>
          </div>
          <div className="divide-y divide-neutral-50 max-h-56 overflow-y-auto">
            {shown.map((e, i) => {
              const m = KIND_META[e.kind] ?? KIND_META.trade;
              return (
                <div key={i} className="flex items-center gap-2 px-3 py-1.5 text-xs">
                  <span className={`w-4 text-center ${m.cls}`}>{m.icon}</span>
                  <span className="flex-1 min-w-0 truncate text-neutral-600">{e.label}</span>
                  <span className={`tabular-nums font-semibold ${e.amount >= 0 ? "text-green-600" : "text-red-500"}`}>
                    {e.amount >= 0 ? "+" : ""}{e.amount.toFixed(2)}
                  </span>
                  <span className="tabular-nums text-neutral-400 w-20 text-right">${e.balance_after.toFixed(2)}</span>
                </div>
              );
            })}
          </div>
          {events.length > 6 && (
            <button onClick={() => setShowAll(v => !v)}
              className="w-full text-[10px] text-neutral-400 hover:text-neutral-600 py-1.5 border-t border-neutral-50">
              {showAll ? "Tampilkan lebih sedikit" : `Tampilkan semua (${events.length})`}
            </button>
          )}
        </div>
      ) : (
        <p className="text-center text-xs text-neutral-400 py-3">Belum ada transaksi. Deposit untuk mulai.</p>
      )}

      {/* Deposit / Withdraw modal */}
      {mode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={e => { if (e.target === e.currentTarget) setMode(null); }}>
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4">
            <h3 className="font-bold text-lg mb-1">{mode === "deposit" ? "Deposit Dana" : "Withdraw Dana"}</h3>
            <p className="text-sm text-neutral-500 mb-4">
              {mode === "deposit"
                ? "Tambah modal ke dompet futures. Agen langsung memakai saldo baru ini untuk sizing."
                : "Tarik dana bebas (tidak termasuk margin yang sedang terkunci posisi terbuka)."}
            </p>
            <label className="text-xs font-medium text-neutral-600 block mb-1">Jumlah (USD)</label>
            <input type="number" min="1" step="100" placeholder="Contoh: 500" value={amt}
              onChange={e => setAmt(e.target.value)} autoFocus
              className="w-full border border-neutral-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400" />
            {info && mode === "withdraw" && (
              <p className="text-[10px] text-neutral-400 mt-1">Dana bebas: ${info.available.toFixed(2)}</p>
            )}
            {err && <p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2 mt-2">{err}</p>}
            <div className="flex gap-2 mt-4">
              <button onClick={() => { setMode(null); setErr(""); }}
                className="flex-1 px-4 py-2 rounded-lg border border-neutral-200 text-sm text-neutral-600 hover:bg-neutral-50">
                Batal
              </button>
              <button onClick={() => void submit()} disabled={busy || !parseFloat(amt)}
                className={`flex-1 px-4 py-2 rounded-lg text-white text-sm font-semibold disabled:opacity-50 ${
                  mode === "deposit" ? "bg-teal-500 hover:bg-teal-600" : "bg-red-500 hover:bg-red-600"}`}>
                {busy ? "Memproses..." : mode === "deposit" ? "Deposit" : "Withdraw"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
