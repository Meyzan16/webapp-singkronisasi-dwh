"use client";
import { usePathname } from "next/navigation";

const pathnameMap = {
  "dashboards": {
    title: "Dashboard",
    description: "Overview of all synchronization activities",
  },
  "sync-jobs": {
    title: "Synchronization Jobs",
    description: "Manage and monitor all synchronization tasks",
  },
  "data-mapping": {
    title: "Data Mapping & Configuration",
    description: "Configure data mapping between source and target systems",
  },
  "monitoring": {
    title: "Monitoring & Logs",
    description: "Track audit trails and system activity logs",
  },
  "settings": {
    title: "Settings & Access",
    description: "Manage system settings and user permissions",
  },
};

const defaultMap = {
  title: "Home",
  description: "Monitor all synchronization activities",
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