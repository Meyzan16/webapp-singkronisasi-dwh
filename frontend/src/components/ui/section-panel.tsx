"use client";
import Link from "next/link";
import type { ReactNode } from "react";

interface SectionPanelProps {
  title: string;
  subtitle?: string;
  badge?: ReactNode;
  action?: { label: string; href: string };
  children: ReactNode;
  className?: string;
  headerClass?: string;
}

export function SectionPanel({ title, subtitle, badge, action, children, className, headerClass }: SectionPanelProps) {
  return (
    <div className={`bg-white rounded-2xl border border-neutral-200 overflow-hidden ${className ?? ""}`}>
      <div className={`flex items-center justify-between px-4 py-3 border-b border-neutral-100 bg-neutral-50 ${headerClass ?? ""}`}>
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="font-bold text-sm text-neutral-700">{title}</h3>
          {badge}
        </div>
        {action && (
          <Link href={action.href} className="text-[10px] text-teal-600 hover:underline font-semibold shrink-0">
            {action.label} →
          </Link>
        )}
        {subtitle && !action && (
          <p className="text-[10px] text-neutral-400">{subtitle}</p>
        )}
      </div>
      {children}
    </div>
  );
}

export function PanelRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 hover:bg-neutral-50 border-b border-neutral-100 last:border-0 ${className ?? ""}`}>
      {children}
    </div>
  );
}
