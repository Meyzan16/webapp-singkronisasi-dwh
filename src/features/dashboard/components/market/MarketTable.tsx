import { fmtPrice, fmtVolBare } from "@/lib/format";
import { getCoinCategory } from "../../data/categories";

interface FuturesTicker {
  symbol: string;
  price: number;
  change_24h: number;
  volume_24h: number;
  high_24h: number;
  low_24h: number;
}

interface MarketTableProps {
  tickers: FuturesTicker[];
  startIndex: number;
  onSelect: (symbol: string) => void;
}

export function MarketTable({ tickers, startIndex, onSelect }: MarketTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-muted-foreground border-b">
            <th className="text-left py-2 pr-3 pl-1">#</th>
            <th className="text-left py-2 pr-3">Symbol</th>
            <th className="text-left py-2 pr-3">Category</th>
            <th className="text-right py-2 pr-3">Price</th>
            <th className="text-right py-2 pr-3">24h %</th>
            <th className="text-right py-2 pr-3">Volume</th>
            <th className="text-right py-2 pr-3">High</th>
            <th className="text-right py-2">Low</th>
          </tr>
        </thead>
        <tbody>
          {tickers.map((t, i) => {
            const base = t.symbol.replace("USDT", "");
            const cat  = getCoinCategory(t.symbol);
            return (
              <tr key={t.symbol} onClick={() => onSelect(t.symbol)}
                className="border-b border-neutral-50 hover:bg-teal-50 cursor-pointer transition-colors group">
                <td className="py-2.5 pr-3 pl-1 text-muted-foreground text-xs">{startIndex + i + 1}</td>
                <td className="py-2.5 pr-3">
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-primarygreen/10 flex items-center justify-center flex-shrink-0">
                      <span className="text-[10px] font-bold text-primarygreen">{base.slice(0, 3)}</span>
                    </div>
                    <div>
                      <span className="font-semibold group-hover:text-primarygreen transition-colors">{base}</span>
                      <span className="text-xs text-muted-foreground">/USDT</span>
                    </div>
                  </div>
                </td>
                <td className="py-2.5 pr-3">
                  <span className="text-xs bg-neutral-100 text-neutral-600 px-2 py-0.5 rounded-full">{cat}</span>
                </td>
                <td className="py-2.5 pr-3 text-right font-mono text-xs font-semibold">
                  ${fmtPrice(t.price)}
                </td>
                <td className={`py-2.5 pr-3 text-right font-bold text-sm ${t.change_24h >= 0 ? "text-green-600" : "text-red-500"}`}>
                  {t.change_24h >= 0 ? "▲" : "▼"} {Math.abs(t.change_24h).toFixed(2)}%
                </td>
                <td className="py-2.5 pr-3 text-right text-xs text-muted-foreground">
                  ${fmtVolBare(t.volume_24h)}
                </td>
                <td className="py-2.5 pr-3 text-right text-xs text-green-600 font-mono">
                  ${fmtPrice(t.high_24h)}
                </td>
                <td className="py-2.5 text-right text-xs text-red-500 font-mono">
                  ${fmtPrice(t.low_24h)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
