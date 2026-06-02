"use client";

import { SettingsIcon, LogOut, BarChart3, TrendingUp, Zap, Grid2X2, LineChart, BookOpen } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useContext } from "react";
import Link from "next/link";
import DottedSeparator from "./ui/dotted-separator";
import { GlobalContext } from "@/app/context";

const routes = [
  {
    label: "Dashboard",
    href: "/dashboards",
    icon: Grid2X2,
    activeIcon: Grid2X2,
  },
  {
    label: "Scanner",
    href: "/scanner",
    icon: BarChart3,
    activeIcon: BarChart3,
  },
  {
    label: "Signal Feed",
    href: "/signals",
    icon: Zap,
    activeIcon: Zap,
  },
  {
    label: "Charts",
    href: "/charts",
    icon: LineChart,
    activeIcon: LineChart,
  },
  {
    label: "Backtest",
    href: "/backtest",
    icon: TrendingUp,
    activeIcon: TrendingUp,
  },
  {
    label: "Architecture",
    href: "/architecture",
    icon: BookOpen,
    activeIcon: BookOpen,
  },
  {
    label: "Settings",
    href: "/settings",
    icon: SettingsIcon,
    activeIcon: SettingsIcon,
  },
];

export const Navigation = () => {
  const pathName = usePathname();
  const router = useRouter();
  const { currentUser, setCurrentUser } = useContext(GlobalContext)!;

  const handleSignOut = () => {
    // TODO: panggil API logout saat sudah terintegrasi
    setCurrentUser(null);
    router.push("/sign-in");
  };

  const userInitials = currentUser?.name
    ? currentUser.name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2)
    : "—";

  return (
    <aside className="flex flex-col h-screen w-64 bg-neutral-100 text-black justify-between border-r border-neutral-300">
      <nav className="px-6">
        <div className="mb-2 text-xs font-semibold text-black">Navigation</div>
        {routes.map((item) => {
          const isActive = pathName === item.href;
          const Icon = isActive ? item.activeIcon : item.icon;
          return (
            <Link key={item.href} href={item.href}>
              <div
                className={`flex items-center gap-3 py-3 rounded-lg font-medium text-sm mb-1 transition-colors ${
                  isActive
                    ? "px-2 bg-primarygreen text-white"
                    : "text-black hover:px-2 hover:bg-neutral-300 hover:text-black"
                }`}
              >
                <Icon className="w-5 h-5" />
                {item.label.split(" (")[0]}
              </div>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto">
        <div className="mb-2">
          <DottedSeparator className="w-full border-black border-dotted" />
        </div>
        <div className="flex items-center gap-3 px-2 py-1">
          {currentUser?.avatar ? (
            <img src={currentUser.avatar} alt={currentUser.name} className="w-8 h-8 rounded-full object-cover" />
          ) : (
            <div className="w-8 h-8 rounded-full bg-primarygreen flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
              {userInitials}
            </div>
          )}
          <div className="flex flex-col min-w-0 flex-1">
            <span className="font-semibold text-sm text-neutral-700 truncate">
              {currentUser?.name ?? "—"}
            </span>
            <span className="text-xs text-neutral-400 truncate">
              {currentUser?.email ?? "Not signed in"}
            </span>
          </div>
          <button
            onClick={handleSignOut}
            title="Sign out"
            className="rounded-full bg-primarygreen p-2 flex-shrink-0 text-white hover:text-red-500 hover:bg-red-50 transition-colors"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
};
