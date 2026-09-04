"use client";
import { apiFetch } from "@/lib/api";
import { useEffect, useState } from "react";

/**
 * PLAN_v5 Group C7 — set of "group.key" strings that exist as editable rows in
 * the agent_config table. Used to badge architecture-page fields as 🔵 DB
 * (editable via Settings) vs ⚪ static (still hardcoded in the agent module).
 */
export function useAgentConfigDbKeys(): Set<string> {
  const [keys, setKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/v1/agent/config/all")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as { agent_group: string; key: string }[];
      })
      .then((rows) => {
        if (cancelled) return;
        setKeys(new Set(rows.map((r) => `${r.agent_group}.${r.key}`)));
      })
      .catch(() => {
        if (!cancelled) setKeys(new Set());
      });
    return () => { cancelled = true; };
  }, []);

  return keys;
}
