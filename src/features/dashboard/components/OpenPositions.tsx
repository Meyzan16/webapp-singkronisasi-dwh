"use client";
import { useEffect, useState, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface Position {
  id: number;
  pair: string;
  side: string;
  entry_price: number;
  current_price: number | null;
  quantity: number;
  leverage: number;
  unrealized_pnl: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  margin: number | null;
}

interface WSData {
  type: string;
  positions: Position[];
  prices: Record<string, { price: number; change_24h: number }>;
  balance: {
    total_balance: number;
    available_balance: number;
    margin_used: number;
  } | null;
  open_count: number;
}

export function OpenPositions() {
  const [data, setData] = useState<WSData | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    function connect() {
      const ws = new WebSocket("ws://localhost:8000/ws/positions");

      ws.onopen = () => {
        setConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as WSData;
          setData(parsed);
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        setConnected(false);
        reconnectRef.current = setTimeout(connect, 5000);
      };

      ws.onerror = () => {
        setConnected(false);
      };

      wsRef.current = ws;
    }

    connect();
    return () => {
      wsRef.current?.close();
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
    };
  }, []);

  const pnlColor = (pnl: number | null) => {
    if (pnl === null) return "text-muted-foreground";
    return pnl >= 0 ? "text-green-600" : "text-red-600";
  };

  return (
    <div className="space-y-4">
      {/* Account Balance */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Futures Account</span>
            <Badge className={connected ? "bg-green-500" : "bg-red-500"}>
              {connected ? "Live" : "Offline"}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data?.balance ? (
            <div className="grid grid-cols-3 gap-4">
              <div>
                <p className="text-xs text-muted-foreground">Total Balance</p>
                <p className="text-lg font-bold">${data.balance.total_balance.toFixed(2)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Available</p>
                <p className="text-lg font-bold">${data.balance.available_balance.toFixed(2)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Margin Used</p>
                <p className="text-lg font-bold">${data.balance.margin_used.toFixed(2)}</p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {connected ? "Loading balance..." : "Connect backend to view balance"}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Live Prices */}
      {data?.prices && Object.keys(data.prices).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Live Prices</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-5 gap-3">
              {Object.entries(data.prices).map(([pair, info]) => (
                <div key={pair} className="text-center p-2 bg-neutral-50 rounded-lg">
                  <p className="text-xs font-bold">{pair}</p>
                  <p className="text-sm font-mono">${info.price.toLocaleString()}</p>
                  <p className={`text-xs ${info.change_24h >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {info.change_24h >= 0 ? "+" : ""}{info.change_24h.toFixed(2)}%
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Open Positions */}
      <Card>
        <CardHeader>
          <CardTitle>Open Positions ({data?.open_count ?? 0})</CardTitle>
        </CardHeader>
        <CardContent>
          {!data?.positions || data.positions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No open positions</p>
          ) : (
            <div className="space-y-3">
              {data.positions.map((pos) => (
                <div
                  key={pos.id}
                  className="flex items-center justify-between p-3 bg-neutral-50 rounded-lg border"
                >
                  <div className="flex items-center gap-3">
                    <Badge className={pos.side === "LONG" ? "bg-green-500" : "bg-red-500"}>
                      {pos.side} {pos.leverage}x
                    </Badge>
                    <div>
                      <p className="font-bold text-sm">{pos.pair}</p>
                      <p className="text-xs text-muted-foreground">
                        Entry: ${pos.entry_price.toLocaleString()} → Current: ${pos.current_price?.toLocaleString() ?? "..."}
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className={`font-bold text-sm ${pnlColor(pos.unrealized_pnl)}`}>
                      {pos.unrealized_pnl !== null
                        ? `${pos.unrealized_pnl >= 0 ? "+" : ""}$${pos.unrealized_pnl.toFixed(2)}`
                        : "—"}
                    </p>
                    <div className="flex gap-2 text-xs text-muted-foreground">
                      {pos.stop_loss && <span>SL: ${pos.stop_loss.toLocaleString()}</span>}
                      {pos.take_profit && <span>TP: ${pos.take_profit.toLocaleString()}</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
