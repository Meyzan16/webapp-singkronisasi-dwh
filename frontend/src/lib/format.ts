// Use "en-US" locale explicitly to prevent SSR/hydration mismatches.
// Never use toLocaleString(undefined) — it uses system locale which differs
// between Node.js server and browser.

export const fmtPrice = (p: number): string =>
  p < 0.001 ? p.toFixed(6)
  : p < 1   ? p.toFixed(4)
  : p < 100 ? p.toLocaleString("en-US", { maximumFractionDigits: 4 })
  :            p.toLocaleString("en-US", { maximumFractionDigits: 2 });

export const fmtPriceShort = (p: number): string =>
  p < 0.001 ? p.toFixed(6)
  : p < 1   ? p.toFixed(4)
  :            p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtVol = (v: number): string =>
  v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B`
  : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M`
  : `$${(v / 1e3).toFixed(0)}K`;

export const fmtVolBare = (v: number): string =>
  v >= 1e9 ? `${(v / 1e9).toFixed(1)}B`
  : v >= 1e6 ? `${(v / 1e6).toFixed(0)}M`
  : `${(v / 1e3).toFixed(0)}K`;
