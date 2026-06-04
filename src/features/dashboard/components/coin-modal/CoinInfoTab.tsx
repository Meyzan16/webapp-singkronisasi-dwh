import { fmtPriceShort, fmtVol } from "@/lib/format";
import type { CoinInfo } from "./types";

interface CoinInfoTabProps { info: CoinInfo; }

export function CoinInfoTab({ info }: CoinInfoTabProps) {
  const rows = [
    { label: "Last Price",    value: `$${fmtPriceShort(info.last_price)}` },
    { label: "Mark Price",    value: `$${fmtPriceShort(info.mark_price)}` },
    { label: "Index Price",   value: `$${fmtPriceShort(info.index_price)}` },
    { label: "24h Change",    value: `${info.change_24h >= 0 ? "+" : ""}${info.change_24h.toFixed(2)}%`, color: info.change_24h >= 0 ? "text-green-600" : "text-red-500" },
    { label: "24h High",      value: `$${fmtPriceShort(info.high_24h)}`,  color: "text-green-600" },
    { label: "24h Low",       value: `$${fmtPriceShort(info.low_24h)}`,   color: "text-red-500"   },
    { label: "Volume (USDT)", value: fmtVol(info.quote_volume_24h) },
    { label: "Open Interest", value: info.open_interest.toLocaleString() },
    { label: "Funding Rate",  value: `${info.funding_rate}%`, color: info.funding_rate >= 0 ? "text-green-600" : "text-red-500" },
    { label: "Trades (24h)",  value: info.count_24h.toLocaleString() },
    { label: "Next Funding",  value: info.next_funding_time ? new Date(info.next_funding_time).toLocaleTimeString() : "—" },
    { label: "Volume (coin)", value: info.volume_24h.toLocaleString() },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
      {rows.map(({ label, value, color }) => (
        <div key={label} className="bg-neutral-50 rounded-xl p-3 border">
          <p className="text-xs text-muted-foreground mb-1">{label}</p>
          <p className={`text-base font-bold ${color ?? ""}`}>{value}</p>
        </div>
      ))}
    </div>
  );
}
