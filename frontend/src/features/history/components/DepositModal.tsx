"use client";

interface DepositModalProps {
  show:           boolean;
  depositAmt:     string;
  depositing:     boolean;
  currentBalance: number;
  onClose:        () => void;
  onAmtChange:    (val: string) => void;
  onDeposit:      () => void;
}

export function DepositModal({
  show, depositAmt, depositing, currentBalance, onClose, onAmtChange, onDeposit,
}: DepositModalProps) {
  if (!show) return null;

  const parsed = parseFloat(depositAmt);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4">
        <h3 className="font-bold text-lg mb-1">Deposit Dana</h3>
        <p className="text-sm text-neutral-500 mb-4">
          Tambah modal ke paper balance. Simulasi deposit nyata — bisa diganti dengan API
          exchange saat go-live.
        </p>
        <div className="mb-4">
          <label className="text-xs font-medium text-neutral-600 block mb-1">
            Jumlah (USD)
          </label>
          <input
            type="number"
            min="1"
            step="100"
            placeholder="Contoh: 500"
            value={depositAmt}
            onChange={e => onAmtChange(e.target.value)}
            className="w-full border border-neutral-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400"
            autoFocus
          />
          {parsed > 0 && (
            <p className="text-xs text-teal-600 mt-1">
              Saldo akan menjadi ${(currentBalance + parsed).toFixed(2)}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-neutral-200 text-sm text-neutral-600 hover:bg-neutral-50"
          >
            Batal
          </button>
          <button
            onClick={onDeposit}
            disabled={depositing || !parsed || parsed <= 0}
            className="flex-1 px-4 py-2 rounded-lg bg-teal-500 text-white text-sm font-semibold hover:bg-teal-600 disabled:opacity-50"
          >
            {depositing ? "Depositing..." : "Deposit"}
          </button>
        </div>
      </div>
    </div>
  );
}
