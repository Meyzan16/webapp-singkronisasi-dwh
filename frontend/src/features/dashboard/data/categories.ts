export const COIN_CATEGORIES: Record<string, string[]> = {
  "Layer 1": [
    "BTC","ETH","SOL","BNB","SUI","ADA","AVAX","DOT","NEAR","APT",
    "TON","TRX","ATOM","ALGO","FTM","ONE","EGLD","HBAR","ICP","FLOW",
    "XLM","VET","EOS","XTZ","THETA","MIOTA","KAVA","ZIL","ICX","ONT",
  ],
  "Layer 2 / Scaling": [
    "MATIC","ARB","OP","IMX","LRC","METIS","BOBA","ZKS","STRK","MANTA",
    "SCROLL","ZKSYNC","LINEA","BLAST","DYDX","SNX","PERP",
  ],
  "DeFi": [
    "UNI","AAVE","LINK","CRV","COMP","MKR","YFI","BAL","SUSHI","1INCH",
    "CAKE","GMX","GNS","JOE","PENDLE","RUNE","OSMO","INJ","SEI","TIA",
    "PYTH","JTO","WEN","BONK",
  ],
  "AI / Data": [
    "FET","AGIX","OCEAN","RENDER","TAO","WLD","GRT","BAND","API3","NMR",
    "ORAI","AKT","HFT","MLT","OPAI","CGPT","MYRIA",
  ],
  "Meme": [
    "DOGE","SHIB","PEPE","FLOKI","BABYDOGE","MEME","LADYS","TURBO","BONK",
    "WIF","BOME","MYRO","SLERF","POPCAT","NEIRO","GOAT","PNUT","ACT",
    "MOODENG","CHILLGUY","FWOG","SPX","SUNDOG","DOGS","HMSTR","CATI",
    "USELESS",
  ],
  "GameFi / Metaverse": [
    "AXS","SAND","MANA","ENJ","GALA","ILV","YGG","MAGIC","LOOKS","BLUR",
    "BEAM","BIGTIME","ECHELON","PIXEL","PORTAL","VANRY","PRIME","ACE",
    "SUPER","WAXP","ALICE","TLM","GHST","SLP","PYR","ATLAS","POLIS",
  ],
  "RWA / Infrastructure": [
    "LINK","GRT","FIL","AR","STORJ","SC","ANKR","LPT","NKN","FLUX","GLM",
    "RLC","ROSE","CTXC","POLS","REEF","EWT","OGN",
  ],
  "Exchange": [
    "BNB","OKB","GT","KCS","HT","MX","BGB","CRO","LEO","FTT","IDEX",
  ],
};

export const ALL_CATEGORIES = ["All", ...Object.keys(COIN_CATEGORIES)];

export function getCoinCategory(symbol: string): string {
  const base = symbol.replace("USDT", "").replace("PERP", "");
  for (const [cat, coins] of Object.entries(COIN_CATEGORIES)) {
    if (coins.includes(base)) return cat;
  }
  return "Others";
}
