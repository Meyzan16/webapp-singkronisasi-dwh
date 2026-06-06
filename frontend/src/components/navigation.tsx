"use client";

import { SettingsIcon, LogOut, Zap, Grid2X2, BookOpen, History, TrendingUp, BarChart2, Activity } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useContext } from "react";
import Link from "next/link";
import DottedSeparator from "./ui/dotted-separator";
import { GlobalContext } from "@/app/context";

const routes = [
  { label: "Dashboard",        href: "/dashboards",   icon: Grid2X2,     group: ""        },
  { label: "Futures Scanner",  href: "/scanner",      icon: Zap,         group: "FUTURES" },
  { label: "Spot Opportunity", href: "/opportunity",  icon: TrendingUp,  group: "SPOT"    },
  { label: "History",          href: "/history",      icon: BarChart2,   group: "ALL"     },
  { label: "System Health",    href: "/system-health", icon: Activity,    group: ""        },
  { label: "Architecture",     href: "/architecture", icon: BookOpen,    group: ""        },
  { label: "Settings",         href: "/settings",     icon: SettingsIcon, group: ""       },
];

export const Navigation = () => {
  const pathName = usePathname();
  const router   = useRouter();
  const { currentUser, setCurrentUser } = useContext(GlobalContext)!;

  const handleSignOut = () => {
    setCurrentUser(null);
    router.push("/sign-in");
  };

  const userInitials = currentUser?.name
    ? currentUser.name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2)
    : "—";

  return (
    <aside className="flex flex-col h-screen w-64 bg-neutral-100 text-black justify-between border-r border-neutral-300">
      <nav className="px-4 pt-2">
        {routes.map((item, idx) => {
          const isActive = pathName === item.href;
          const Icon = item.icon;
          // Show group label before first item of each group
          const prevGroup = idx > 0 ? routes[idx - 1].group : "__none__";
          const showGroupLabel = item.group && item.group !== prevGroup;
          return (
            <div key={item.href}>
              {showGroupLabel && (
                <div className={`mt-3 mb-1 px-2 text-[10px] font-bold uppercase tracking-widest ${
                  item.group === "FUTURES" ? "text-blue-500"
                  : item.group === "SPOT"  ? "text-teal-600"
                  :                          "text-neutral-400"
                }`}>
                  {item.group === "FUTURES" ? "⚡ Futures"
                  : item.group === "SPOT"   ? "🎯 Spot"
                  :                           "📋 Riwayat"}
                </div>
              )}
              {!item.group && idx === 0 && (
                <div className="mb-1 px-2 text-[10px] font-bold uppercase tracking-widest text-neutral-400">
                  Menu
                </div>
              )}
              <Link href={item.href}>
                <div className={`flex items-center gap-3 py-2.5 rounded-lg font-medium text-sm mb-0.5 transition-colors ${
                  isActive
                    ? "px-2 bg-primarygreen text-white"
                    : "text-black hover:px-2 hover:bg-neutral-300 hover:text-black"
                }`}>
                  <Icon className="w-4 h-4 shrink-0" />
                  {item.label}
                </div>
              </Link>
            </div>
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
            className="rounded-full bg-primarygreen p-2 flex-shrink-0 text-white hover:text-red-500 hover:bg-red-50 transition-colors">
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
};
