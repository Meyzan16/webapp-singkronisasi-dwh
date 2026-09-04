"use client";
import { apiFetch, HEAVY_TIMEOUT_MS } from "@/lib/api";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";

type ResetSummary = {
  ok:               boolean;
  preserve_initial: boolean;
  wiped:            Record<string, number>;
  caches_cleared:   string[];
  ts:               number;
};

export function DBResetCard() {
  const [confirmText,      setConfirmText]    = useState("");
  const [preserveInitial,  setPreserve]       = useState(true);
  const [busy,             setBusy]           = useState(false);
  const [result,           setResult]         = useState<ResetSummary | null>(null);
  const [error,            setError]          = useState<string | null>(null);

  const armed = confirmText === "RESET";

  const handleReset = async () => {
    if (!armed) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const r = await apiFetch("/api/v1/admin/reset_simulation", {
        timeoutMs: HEAVY_TIMEOUT_MS,
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          confirm: "RESET_ALL",
          preserve_initial_deposit: preserveInitial,
        }),
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(`HTTP ${r.status}: ${txt.slice(0, 200)}`);
      }
      const data: ResetSummary = await r.json();
      setResult(data);
      setConfirmText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="border-red-200">
      <CardContent className="pt-6 space-y-4">
        <div>
          <h3 className="font-bold text-red-700 mb-1">⚠ Reset Simulation Data</h3>
          <p className="text-xs text-neutral-600 leading-relaxed">
            Hapus semua paper trades, signal weights, balance transactions, big mover log,
            force-open log, weekly backtest, dan health events. Cache adaptive learning
            (weight, blacklist, win rate per coin) juga ter-clear di memory.
            Backup pg_dump direkomendasikan sebelum eksekusi.
          </p>
        </div>

        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={preserveInitial}
            onChange={(e) => setPreserve(e.target.checked)}
          />
          <span>Preserve paper_balances (reset balance ke initial + deposit − withdraw, jangan delete row)</span>
        </label>

        <div className="space-y-1">
          <label className="text-xs font-medium text-neutral-700">
            Ketik <span className="font-mono font-bold">RESET</span> untuk mengaktifkan tombol:
          </label>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="RESET"
            className="w-full px-3 py-2 border border-neutral-300 rounded-lg text-sm font-mono"
            disabled={busy}
          />
        </div>

        <button
          onClick={handleReset}
          disabled={!armed || busy}
          className={`w-full p-3 rounded-lg font-semibold text-sm transition-colors ${
            armed && !busy
              ? "bg-red-600 text-white hover:bg-red-700"
              : "bg-neutral-200 text-neutral-400 cursor-not-allowed"
          }`}
        >
          {busy ? "Resetting…" : armed ? "🗑 Reset Simulation Data" : "Type RESET to enable"}
        </button>

        {error && (
          <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg p-3">
            <p className="font-semibold mb-1">Error</p>
            <pre className="whitespace-pre-wrap">{error}</pre>
          </div>
        )}

        {result && (
          <div className="text-xs text-green-800 bg-green-50 border border-green-200 rounded-lg p-3 space-y-2">
            <p className="font-semibold">✓ Reset complete</p>
            <div>
              <p className="font-semibold mb-0.5">Rows wiped:</p>
              <ul className="list-disc list-inside font-mono">
                {Object.entries(result.wiped).map(([t, n]) => (
                  <li key={t}>{t}: <span className={n < 0 ? "text-neutral-500" : ""}>{n < 0 ? "(skipped)" : n}</span></li>
                ))}
              </ul>
            </div>
            <div>
              <p className="font-semibold mb-0.5">Caches cleared:</p>
              <ul className="list-disc list-inside font-mono">
                {result.caches_cleared.map((c) => <li key={c}>{c}</li>)}
              </ul>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
