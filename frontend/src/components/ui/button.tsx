"use client";

import React from "react";
import { twMerge } from "tailwind-merge";

interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:
    | "primary"
    | "destructive"
    | "outline"
    | "secondary"
    | "muted"
    | "teritrary";
  size?: "sm" | "md" | "lg" | "icon";
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", children, ...props }, ref) => {
    const baseClasses =
      " inline-flex items-center font-Poppins justify-center gap-2 rounded-2xl font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:pointer-events-none disabled:bg-neutral-100 disabled:from-neutral-100 disabled:to-neutral-100 disabled:text-neutral-300 border border-neutral-200 shadow-sm ";

    const variantClasses = {
      primary: "bg-primarygreen text-white text-primary-foreground",
      destructive: "bg-primaryorange text-white text-primary-foreground",
      outline: "border border-gray-300 bg-white text-gray-700 hover:bg-gray-100",
      secondary: "bg-gray-200 text-dark hover:bg-gray-300",
      muted: "bg-neutral-200 text-neutral-600 hover:bg-neutral-200/80",
      teritrary: "bg-blue-200 text-blue-600 border-transparent shadow-none",
    };

    const sizeClasses = {
      sm: "px-3 py-1 text-sm",
      md: "px-4 py-2 text-base",
      lg: "px-6 py-3 text-lg",
      icon: "p-2 w-10 h-10 flex items-center justify-center",
    };

    return (
      <button
        ref={ref}
        className={twMerge(
          baseClasses,
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        {...props}
      >
        {children}
      </button>
    );
  },
);

Button.displayName = "Button";

