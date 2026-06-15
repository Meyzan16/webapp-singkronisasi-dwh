"use client";

export function EmptyState({ icon = "📭", title, subtitle }: {
  icon?: string; title: string; subtitle?: string;
}) {
  return (
    <div className="py-10 text-center text-neutral-400">
      <p className="text-2xl mb-1">{icon}</p>
      <p className="text-sm font-medium text-neutral-500">{title}</p>
      {subtitle && <p className="text-xs text-neutral-400 mt-0.5">{subtitle}</p>}
    </div>
  );
}

export function LoadingSpinner({ size = "md", className }: {
  size?: "sm" | "md" | "lg"; className?: string;
}) {
  const s = size === "sm" ? "w-4 h-4" : size === "lg" ? "w-12 h-12" : "w-8 h-8";
  return (
    <div className={`${s} border-2 border-teal-400 border-t-transparent rounded-full animate-spin ${className ?? ""}`} />
  );
}

export function LoadingPage({ message = "Memuat..." }: { message?: string }) {
  return (
    <div className="py-16 text-center text-neutral-400">
      <LoadingSpinner size="lg" className="mx-auto mb-3" />
      <p className="text-sm">{message}</p>
    </div>
  );
}
