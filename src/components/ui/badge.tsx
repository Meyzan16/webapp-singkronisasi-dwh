"use client";

import React from "react";
import { JobStatus } from "@/utilities/types";

interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "secondary" | "destructive" | "outline" | JobStatus;
}

const jobStatusVariantClasses: Record<JobStatus, string> = {
  running: "border-transparent bg-blue-100 text-blue-800",
  success: "border-transparent bg-emerald-100 text-emerald-800",
  failed: "border-transparent bg-rose-100 text-rose-800",
};


const Badge: React.FC<BadgeProps> = ({ variant = "default", className, ...props }) => {
  const baseClasses =
    "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2";

  let variantClasses = "";

  if (variant === "secondary") {
    variantClasses = "border-transparent bg-secondaryDefault text-white hover:bg-secondary/80";
  } else if (variant === "destructive") {
    variantClasses = "border-transparent bg-destructive text-destructive-foreground shadow hover:bg-destructive/80";
  } else if (variant === "outline") {
    variantClasses = "text-foreground border border-gray-300";
  } else if ((["running", "success", "failed"] as JobStatus[]).includes(variant as JobStatus)) {
    variantClasses = jobStatusVariantClasses[variant as JobStatus];
  } else {
    variantClasses = "border-transparent bg-primaryGreen text-primary-foreground shadow hover:bg-primary/80";
  }

  return (
    <div className={`${baseClasses} ${variantClasses} ${className || ""}`} {...props} />
  );
};

export { Badge };
