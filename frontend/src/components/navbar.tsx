"use client";
import { usePathname } from "next/navigation";

const pathnameMap = {
  "dashboards": {
    title: "Dashboard",
    description: "Portfolio summary & active signals",
  },
  "scanner": {
    title: "⚡ Futures Scanner",
    description: "Agent 1 (AI Knowledge) + Agent 2 (T0-T4) · 100 USDT-M Perpetual pairs · LONG & SHORT",
  },
  "opportunity": {
    title: "🎯 Spot Opportunity",
    description: "Spot scanner — BB Squeeze · Accumulation · Breakout · Entry/SL/TP otomatis",
  },
  "history": {
    title: "📋 History",
    description: "Paper trading history — Spot Scanner · Spot Opportunity · Futures Agent 1+2",
  },
  "signals": {
    title: "Signal Feed",
    description: "Live trading signals with entry/SL/TP",
  },
  "charts": {
    title: "Charts",
    description: "Technical analysis with EMA & S/R zones",
  },
  "backtest": {
    title: "Backtest",
    description: "Strategy testing against historical data",
  },
  "system-health": {
    title: "⚙️ System Health",
    description: "Real-time monitoring — semua agents, API Binance, database",
  },
  "architecture": {
    title: "📐 Architecture",
    description: "6 autonomous agents · 2 sistem independen · Futures AI + T0-T4 · Spot Opportunity",
  },
  "settings": {
    title: "Settings",
    description: "Agent configuration & risk rules",
  },
};

const defaultMap = {
  title: "Crypto Trading Agent",
  description: "AI-powered multi-timeframe technical analysis",
};

export const Navbar = () => {
    const pathName = usePathname();
    const pathnameParts = pathName.split("/");
    const pathnamekey = pathnameParts[1] as keyof typeof pathnameMap;

    const {title, description} = pathnameMap[pathnamekey] || defaultMap;


    return (
        <nav className="pt-4 px-6 flex items-center justify-between">
            <div className="flex-col hidden lg:flex ">
                <h1 className="text-2xl font-semibold">{title}</h1>
                <p className="text-muted-foreground">{description}</p>
            </div>
        </nav>
    )
}