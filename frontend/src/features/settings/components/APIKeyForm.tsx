"use client";
import { apiFetch, HEAVY_TIMEOUT_MS } from "@/lib/api";
import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

// ── Types ─────────────────────────────────────────────────────────────────────

interface KeyStatus {
  has_key:    boolean;
  has_secret: boolean;
  masked_key: string;
  updated_at: number | null;
  source:     "database" | "env";
}

interface TestResult {
  success:           boolean;
  message:           string;
  account_type?:     string;
  can_trade?:        boolean;
  spot_balance_usdt?: number;
  total_assets?:     number;
}

interface SpotBalance {
  asset:  string;
  free:   number;
  locked: number;
  total:  number;
}

interface SpotWallet {
  error?:        string;
  message?:      string;
  account_type?: string;
  can_trade?:    boolean;
  balances:      SpotBalance[];
  total_assets?: number;
  fetched_at?:   number;
}

// ── Main Component ────────────────────────────────────────────────────────────

export function APIKeyForm() {
  const [apiKey,    setApiKey]    = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [showKey,   setShowKey]   = useState(false);
  const [showSec,   setShowSec]   = useState(false);

  const [keyStatus,  setKeyStatus]  = useState<KeyStatus | null>(null);
  const [saving,     setSaving]     = useState(false);
  const [saveMsg,    setSaveMsg]    = useState<{ ok: boolean; text: string } | null>(null);
  const [testing,    setTesting]    = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [wallet,     setWallet]     = useState<SpotWallet | null>(null);
  const [loadingWallet, setLoadingWallet] = useState(false);

  // ── Load saved key status on mount ────────────────────────────────────────

  const loadKeyStatus = useCallback(async () => {
    try {
      const r = await apiFetch("/api/v1/exchange/keys");
      if (r.ok) setKeyStatus(await r.json() as KeyStatus);
    } catch { /* backend offline */ }
  }, []);

  const loadWallet = useCallback(async () => {
    setLoadingWallet(true);
    try {
      const r = await apiFetch("/api/v1/wallet/spot");
      if (r.ok) setWallet(await r.json() as SpotWallet);
    } catch { /* ignore */ }
    finally { setLoadingWallet(false); }
  }, []);

  useEffect(() => {
    void loadKeyStatus();
    void loadWallet();
  }, [loadKeyStatus, loadWallet]);

  // ── Save to DB ────────────────────────────────────────────────────────────

  const handleSave = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) {
      setSaveMsg({ ok: false, text: "Isi API Key dan Secret Key terlebih dahulu." });
      return;
    }
    setSaving(true);
    setSaveMsg(null);
    try {
      const r = await apiFetch("/api/v1/exchange/keys", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ api_key: apiKey.trim(), api_secret: apiSecret.trim() }),
      });
      const d = await r.json() as { saved?: boolean; message?: string };
      if (r.ok && d.saved) {
        setSaveMsg({ ok: true, text: "✅ Credentials tersimpan di database!" });
        setApiKey("");
        setApiSecret("");
        await loadKeyStatus();
        await loadWallet();
      } else {
        setSaveMsg({ ok: false, text: d.message ?? "Gagal menyimpan." });
      }
    } catch {
      setSaveMsg({ ok: false, text: "Network error — backend tidak dapat dijangkau." });
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 5000);
    }
  };

  // ── Test connection ───────────────────────────────────────────────────────

  const handleTest = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) {
      setTestResult({ success: false, message: "Isi API Key dan Secret Key untuk test." });
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const r = await apiFetch("/api/v1/account/test-connection", {
        timeoutMs: HEAVY_TIMEOUT_MS,
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ api_key: apiKey.trim(), api_secret: apiSecret.trim() }),
      });
      const d = await r.json() as TestResult;
      setTestResult(d);
    } catch {
      setTestResult({ success: false, message: "Network error — backend tidak berjalan." });
    } finally {
      setTesting(false);
    }
  };

  const fmtDate = (ts: number) =>
    new Date(ts * 1000).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });

  return (
    <div className="space-y-4">
      {/* ── Saved key status ────────────────────────────────────────────────── */}
      {keyStatus && (
        <Card className="border-neutral-200">
          <CardContent className="pt-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm font-semibold text-neutral-700">Status Credentials:</span>
              {keyStatus.has_key ? (
                <Badge className="bg-green-100 text-green-700 border border-green-200">
                  ✓ API Key tersimpan
                </Badge>
              ) : (
                <Badge className="bg-neutral-100 text-neutral-500 border border-neutral-200">
                  Belum ada API Key
                </Badge>
              )}
              {keyStatus.has_secret ? (
                <Badge className="bg-green-100 text-green-700 border border-green-200">
                  ✓ Secret tersimpan
                </Badge>
              ) : (
                <Badge className="bg-neutral-100 text-neutral-500 border border-neutral-200">
                  Belum ada Secret
                </Badge>
              )}
              <Badge className={`border ${keyStatus.source === "database" ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-yellow-50 text-yellow-700 border-yellow-200"}`}>
                {keyStatus.source === "database" ? "📦 Database" : "📄 .env"}
              </Badge>
            </div>
            {keyStatus.masked_key && (
              <p className="text-xs text-neutral-400 font-mono mt-2">{keyStatus.masked_key}</p>
            )}
            {keyStatus.updated_at && (
              <p className="text-[11px] text-neutral-400 mt-1">
                Terakhir diperbarui: {fmtDate(keyStatus.updated_at)}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Input form ────────────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Binance API Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="bg-blue-50 border border-blue-200 p-3 rounded-lg">
            <p className="text-xs text-blue-900">
              <strong>Simpan ke Database:</strong> Credentials disimpan di PostgreSQL —
              tetap ada saat container restart. Tidak perlu ubah <code>.env</code>.
            </p>
          </div>

          {/* API Key */}
          <div>
            <label className="text-sm font-semibold block mb-2">API Key</label>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                placeholder={keyStatus?.has_key ? "••••• (sudah tersimpan, input baru untuk update)" : "Masukkan Binance API Key"}
                value={apiKey}
                onChange={e => { setApiKey(e.target.value); setTestResult(null); }}
                className="w-full p-2 pr-10 border rounded-lg font-mono text-xs"
              />
              <button
                type="button"
                onClick={() => setShowKey(v => !v)}
                className="absolute right-2 top-2 text-neutral-400 hover:text-neutral-700 text-xs"
              >
                {showKey ? "🙈" : "👁"}
              </button>
            </div>
          </div>

          {/* Secret Key */}
          <div>
            <label className="text-sm font-semibold block mb-2">Secret Key</label>
            <div className="relative">
              <input
                type={showSec ? "text" : "password"}
                placeholder={keyStatus?.has_secret ? "••••• (sudah tersimpan, input baru untuk update)" : "Masukkan Binance Secret Key"}
                value={apiSecret}
                onChange={e => { setApiSecret(e.target.value); setTestResult(null); }}
                className="w-full p-2 pr-10 border rounded-lg font-mono text-xs"
              />
              <button
                type="button"
                onClick={() => setShowSec(v => !v)}
                className="absolute right-2 top-2 text-neutral-400 hover:text-neutral-700 text-xs"
              >
                {showSec ? "🙈" : "👁"}
              </button>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex gap-3">
            <button
              onClick={handleTest}
              disabled={testing || (!apiKey && !keyStatus?.has_key)}
              className="flex-1 p-3 rounded-lg font-semibold text-sm border-2 border-primarygreen text-primarygreen hover:bg-primarygreen hover:text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {testing ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin inline-block w-4 h-4 border-2 border-primarygreen border-t-transparent rounded-full" />
                  Testing...
                </span>
              ) : "🔌 Test Connection"}
            </button>

            <button
              onClick={handleSave}
              disabled={saving || !apiKey.trim() || !apiSecret.trim()}
              className="flex-1 p-3 rounded-lg font-semibold text-sm bg-primarygreen text-white hover:bg-teal-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {saving ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                  Menyimpan...
                </span>
              ) : "💾 Simpan ke Database"}
            </button>
          </div>

          {/* Save message */}
          {saveMsg && (
            <div className={`p-3 rounded-lg border text-sm font-semibold ${saveMsg.ok ? "bg-green-50 border-green-200 text-green-800" : "bg-red-50 border-red-200 text-red-800"}`}>
              {saveMsg.text}
            </div>
          )}

          {/* Test result */}
          {testResult && (
            <div className={`p-4 rounded-lg border ${testResult.success ? "bg-green-50 border-green-300" : "bg-red-50 border-red-300"}`}>
              <div className="flex items-start gap-2">
                <span className="text-lg">{testResult.success ? "✅" : "❌"}</span>
                <div className="flex-1">
                  <p className={`text-sm font-semibold ${testResult.success ? "text-green-800" : "text-red-800"}`}>
                    {testResult.message}
                  </p>
                  {testResult.success && (
                    <div className="mt-2 space-y-1">
                      {testResult.account_type && (
                        <p className="text-xs text-green-700">Account: <strong>{testResult.account_type}</strong></p>
                      )}
                      {testResult.can_trade !== undefined && (
                        <p className="text-xs text-green-700">Trading: <strong>{testResult.can_trade ? "Aktif ✓" : "Tidak aktif ✗"}</strong></p>
                      )}
                      {testResult.spot_balance_usdt !== undefined && (
                        <p className="text-xs text-green-700">USDT Balance: <strong>${testResult.spot_balance_usdt.toLocaleString()}</strong></p>
                      )}
                      {testResult.total_assets !== undefined && (
                        <p className="text-xs text-green-700">Total aset non-zero: <strong>{testResult.total_assets}</strong></p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Security note */}
          <div className="bg-amber-50 border border-amber-200 p-3 rounded-lg">
            <p className="text-xs text-amber-900">
              <strong>Security:</strong> Credentials disimpan plaintext di PostgreSQL.
              Pastikan database tidak exposed ke publik. Jangan aktifkan &quot;Enable Withdrawals&quot; di Binance.
              Restrict IP ke server kamu saja.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* ── Real Spot Holdings ─────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Real Spot Holdings</CardTitle>
            <button
              onClick={loadWallet}
              disabled={loadingWallet}
              className="text-xs text-primarygreen hover:underline font-semibold disabled:opacity-40"
            >
              {loadingWallet ? "Memuat..." : "↺ Refresh"}
            </button>
          </div>
        </CardHeader>
        <CardContent>
          {loadingWallet ? (
            <div className="flex items-center justify-center py-8 gap-2 text-neutral-400">
              <div className="w-4 h-4 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
              Mengambil data dari Binance...
            </div>
          ) : wallet?.error ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4 text-center space-y-2">
              <p className="text-2xl">🔑</p>
              <p className="text-sm font-bold text-yellow-800">
                {wallet.error === "no_credentials" ? "API Key belum tersimpan" : "Gagal mengambil data"}
              </p>
              <p className="text-xs text-yellow-700">{wallet.message}</p>
            </div>
          ) : wallet && wallet.balances.length > 0 ? (
            <div className="space-y-3">
              {/* Summary */}
              <div className="flex flex-wrap gap-3">
                <div className="bg-neutral-50 border border-neutral-200 rounded-xl px-4 py-2 text-center">
                  <p className="text-xl font-black text-teal-600">{wallet.total_assets}</p>
                  <p className="text-[10px] text-neutral-400 uppercase font-semibold">Aset</p>
                </div>
                <div className="bg-neutral-50 border border-neutral-200 rounded-xl px-4 py-2 text-center">
                  <p className="text-sm font-bold text-green-600">{wallet.can_trade ? "✓ Trading Aktif" : "✗ Trading Off"}</p>
                  <p className="text-[10px] text-neutral-400 uppercase font-semibold">{wallet.account_type}</p>
                </div>
                {wallet.fetched_at && (
                  <div className="bg-neutral-50 border border-neutral-200 rounded-xl px-4 py-2">
                    <p className="text-[10px] text-neutral-400 uppercase font-semibold">Update</p>
                    <p className="text-xs text-neutral-600">{new Date(wallet.fetched_at * 1000).toLocaleTimeString("id-ID")}</p>
                  </div>
                )}
              </div>

              {/* Balance table */}
              <div className="overflow-hidden rounded-xl border border-neutral-200">
                <div className="grid grid-cols-4 px-3 py-2 bg-neutral-50 border-b border-neutral-200 text-[10px] font-bold text-neutral-400 uppercase tracking-wider">
                  <span>Aset</span>
                  <span className="text-right">Free</span>
                  <span className="text-right">Locked</span>
                  <span className="text-right">Total</span>
                </div>
                <div className="divide-y divide-neutral-100 max-h-64 overflow-y-auto">
                  {wallet.balances.map(b => (
                    <div key={b.asset} className="grid grid-cols-4 px-3 py-2 items-center hover:bg-neutral-50">
                      <span className="text-xs font-bold text-neutral-800">{b.asset}</span>
                      <span className="text-xs text-right tabular-nums text-neutral-600">{b.free.toLocaleString(undefined, { maximumFractionDigits: 6 })}</span>
                      <span className="text-xs text-right tabular-nums text-neutral-400">{b.locked > 0 ? b.locked.toLocaleString(undefined, { maximumFractionDigits: 6 }) : "—"}</span>
                      <span className="text-xs text-right tabular-nums font-semibold text-neutral-800">{b.total.toLocaleString(undefined, { maximumFractionDigits: 6 })}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="text-center py-8 text-neutral-400 text-sm">
              Tidak ada aset dengan saldo &gt; 0
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
