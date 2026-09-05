"use client";
import { apiFetch } from "@/lib/api";
import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ConfigRow {
  id: number;
  agent_group: string;
  key: string;
  value: number;
  default: number;
  modified: boolean;
  description: string;
  category: string;
  updated_at: number;
  updated_by: string;
}

const GROUP_LABEL: Record<string, string> = {
  spot: "🎯 SPOT",
  futures: "⚡ FUTURES",
  learning: "🧠 Learning",
};

const CATEGORY_COLOR: Record<string, string> = {
  threshold: "bg-blue-50 text-blue-700",
  volume: "bg-teal-50 text-teal-700",
  quota: "bg-purple-50 text-purple-700",
  risk: "bg-red-50 text-red-700",
  timing: "bg-amber-50 text-amber-700",
  // PLAN-FUTURES-AGENTIC Fase 0/1a: rantai ukuran (risk/notional/leverage/margin)
  // dan saklar penyalaan bertahap. Diberi warna sendiri karena keduanya menyentuh
  // besaran uang per posisi — bukan sekadar ambang tampilan.
  sizing: "bg-emerald-50 text-emerald-700",
  rollout: "bg-fuchsia-50 text-fuchsia-700",
};

function EditableRow({ row, onSaved }: { row: ConfigRow; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(row.value));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    const num = Number(draft);
    if (Number.isNaN(num)) {
      setErr("Bukan angka valid");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const r = await apiFetch(`/api/v1/agent/config/${row.agent_group}/${row.key}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: num }),
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 150));
      }
      setEditing(false);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await apiFetch(`/api/v1/agent/config/${row.agent_group}/${row.key}/reset`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(await r.text());
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`grid grid-cols-12 gap-2 items-center px-3 py-2.5 text-xs ${row.modified ? "bg-amber-50/50" : ""}`}>
      <div className="col-span-3">
        <p className="font-mono font-semibold text-neutral-800">{row.key}</p>
        <p className="text-[10px] text-neutral-500 leading-snug mt-0.5">{row.description}</p>
      </div>
      <div className="col-span-1">
        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${CATEGORY_COLOR[row.category] ?? "bg-neutral-100 text-neutral-600"}`}>
          {row.category}
        </span>
      </div>
      <div className="col-span-2">
        {editing ? (
          <input
            type="number"
            step="any"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full px-2 py-1 border border-neutral-300 rounded text-xs font-mono"
            disabled={busy}
            autoFocus
          />
        ) : (
          <span className="font-mono font-bold text-neutral-900">{row.value}</span>
        )}
      </div>
      <div className="col-span-1">
        <span className="font-mono text-neutral-400">{row.default}</span>
      </div>
      <div className="col-span-1">
        {row.modified && (
          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-orange-100 text-orange-700">
            modified
          </span>
        )}
      </div>
      <div className="col-span-4 flex justify-end gap-1.5">
        {err && <span className="text-[10px] text-red-600 self-center mr-1">{err}</span>}
        {editing ? (
          <>
            <button
              onClick={save}
              disabled={busy}
              className="px-2.5 py-1 rounded-lg bg-teal-600 text-white text-[11px] font-semibold hover:bg-teal-700 disabled:opacity-50"
            >
              {busy ? "…" : "Save"}
            </button>
            <button
              onClick={() => { setEditing(false); setDraft(String(row.value)); setErr(null); }}
              disabled={busy}
              className="px-2.5 py-1 rounded-lg bg-neutral-100 text-neutral-600 text-[11px] font-semibold hover:bg-neutral-200"
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => setEditing(true)}
              className="px-2.5 py-1 rounded-lg bg-neutral-100 text-neutral-700 text-[11px] font-semibold hover:bg-neutral-200"
            >
              Edit
            </button>
            {row.modified && (
              <button
                onClick={reset}
                disabled={busy}
                className="px-2.5 py-1 rounded-lg bg-red-50 text-red-600 text-[11px] font-semibold hover:bg-red-100 disabled:opacity-50"
              >
                Reset
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export function AgentConfigEditor() {
  const [rows, setRows] = useState<ConfigRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeGroup, setActiveGroup] = useState<string>("spot");

  const load = useCallback(() => {
    apiFetch("/api/v1/agent/config/all")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as ConfigRow[];
      })
      .then((data) => { setRows(data); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);

  const groups = rows ? Array.from(new Set(rows.map((r) => r.agent_group))) : [];
  const visible = rows?.filter((r) => r.agent_group === activeGroup) ?? [];
  const modifiedCount = rows?.filter((r) => r.modified).length ?? 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>⚙️ Agent Config</CardTitle>
            <p className="text-xs text-neutral-500 mt-1">
              Ubah threshold, volume, quota, dan risk cap tanpa redeploy — agent membaca perubahan
              dalam ≤60 detik (cache TTL).
            </p>
          </div>
          {modifiedCount > 0 && (
            <span className="text-[10px] font-bold px-2 py-1 rounded-full bg-orange-100 text-orange-700">
              {modifiedCount} modified
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {error && (
          <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg p-3 mb-3">
            Gagal memuat config: {error}
          </div>
        )}
        {!rows && !error && (
          <p className="text-xs text-neutral-400">Memuat…</p>
        )}
        {rows && (
          <>
            <div className="flex gap-1.5 mb-3">
              {groups.map((g) => (
                <button
                  key={g}
                  onClick={() => setActiveGroup(g)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                    activeGroup === g
                      ? "bg-neutral-900 text-white"
                      : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200"
                  }`}
                >
                  {GROUP_LABEL[g] ?? g}
                </button>
              ))}
            </div>

            <div className="rounded-xl border border-neutral-200 overflow-hidden">
              <div className="grid grid-cols-12 gap-2 px-3 py-2 bg-neutral-100 text-[10px] font-bold text-neutral-500 uppercase tracking-wide">
                <div className="col-span-3">Key</div>
                <div className="col-span-1">Category</div>
                <div className="col-span-2">Current</div>
                <div className="col-span-1">Default</div>
                <div className="col-span-1"></div>
                <div className="col-span-4 text-right">Actions</div>
              </div>
              <div className="divide-y divide-neutral-100">
                {visible.map((row) => (
                  <EditableRow key={row.id} row={row} onSaved={load} />
                ))}
                {visible.length === 0 && (
                  <p className="text-xs text-neutral-400 px-3 py-4 text-center">Tidak ada config di group ini.</p>
                )}
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
