export const fmtPrice = (p: number): string =>
  p < 0.001 ? p.toFixed(6) : p < 1 ? p.toFixed(4) : p.toLocaleString(undefined, { maximumFractionDigits: 4 });

export const fmtPriceShort = (p: number): string =>
  p < 0.001 ? p.toFixed(6) : p < 1 ? p.toFixed(4) : p.toLocaleString(undefined, { minimumFractionDigits: 2 });

export const fmtVol = (v: number): string =>
  v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${(v / 1e3).toFixed(0)}K`;

export const fmtVolBare = (v: number): string =>
  v >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : `${(v / 1e3).toFixed(0)}K`;
