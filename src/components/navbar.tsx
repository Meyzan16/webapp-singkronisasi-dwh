"use client";
import { usePathname } from "next/navigation";

const pathnameMap = {
  "dashboards": {
    title: "Dashboard",
    description: "Portfolio summary & active signals",
  },
  "scanner": {
    title: "Scanner",
    description: "Volume heatmap & top movers",
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