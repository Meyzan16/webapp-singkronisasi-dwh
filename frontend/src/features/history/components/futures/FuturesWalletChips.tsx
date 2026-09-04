"use client";
import { apiFetch } from "@/lib/api";
import { useCallback, useEffect, useState } from "react";

// PLAN_v12 P6-F0 — versi RINGKAS pengganti panel "Dompet Futures":
// hanya info unik (Bebas/Terkunci margin) + aksi Deposit/Withdraw, di header banner.
// Saldo/Posisi/Riwayat dibuang (sudah ada di balance banner + equity chart).

interface WalletInfo {
  balance:        number;
  available:      number;
  locked_margin:  number;
  open_positions: number;
}

export function FuturesWalletChips({ onChanged }: { onChanged?: () => void }) {
  const [info, setInfo] = useState<WalletInfo | null>(null);
  const [mode, setMode] = useState<null | "deposit" | "withdraw">(null);
  const [amt,  setAmt]  = useState("");
  const [busy, setBusy] = useState(false);
  const [err,  setErr]  = useState("");

  const refresh = useCallback(async () => {
    try {
      const r = await apiFetch("/api/v1/balance/futures");
      if (r.ok) setInfo(await r.json() as WalletInfo);
    } catch { /* silent */ }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const submit = useCallback(async () => {
    const value = parseFloat(amt);
    if (!value || value <= 0) return;
    setBusy(true); setErr("");
    try {
      const ep = mode === "withdraw" ? "withdraw" : "deposit";
      const r  = await apiFetch(`/api/v1/balance/futures/${ep}`, {
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

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {info && (
        <>
          <span className="text-[10px] bg-white/5 rounded-lg px-2 py-1 text-neutral-300">
            Bebas <strong className="text-green-400 tabular-nums">${info.available.toFixed(0)}</strong>
          </span>
          <span className="text-[10px] bg-white/5 rounded-lg px-2 py-1 text-neutral-300">
            Terkunci <strong className="text-orange-400 tabular-nums">${info.locked_margin.toFixed(0)}</strong>
          </span>
        </>
      )}
      <button onClick={() => { setMode("deposit"); setAmt(""); setErr(""); }}
        className="text-[10px] bg-teal-600 hover:bg-teal-500 text-white font-semibold px-2.5 py-1 rounded-lg">
        + Deposit
      </button>
      <button onClick={() => { setMode("withdraw"); setAmt(""); setErr(""); }}
        className="text-[10px] bg-white/10 hover:bg-white/20 text-neutral-200 font-semibold px-2.5 py-1 rounded-lg">
        − Withdraw
      </button>

      {mode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={e => { if (e.target === e.currentTarget) setMode(null); }}>
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4 text-neutral-800">
            <h3 className="font-bold text-lg mb-1">{mode === "deposit" ? "Deposit Dana" : "Withdraw Dana"}</h3>
            <p className="text-sm text-neutral-500 mb-4">
              {mode === "deposit"
                ? "Tambah modal ke dompet futures. Agen langsung memakai saldo baru untuk sizing."
                : "Tarik dana bebas (tidak termasuk margin yang terkunci di posisi terbuka)."}
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
