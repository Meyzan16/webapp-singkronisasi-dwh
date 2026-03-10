"use client";

import * as React from "react";

const Card = ({ className = "", children }: { className?: string; children: React.ReactNode }) => (
  <div className={`rounded-xl border bg-card text-card-foreground shadow ${className}`}>
    {children}
  </div>
);

const CardHeader = ({ className = "", children }: { className?: string; children: React.ReactNode }) => (
  <div className={`p-6 ${className}`}>{children}</div>
);

const CardTitle = ({ className = "", children }: { className?: string; children: React.ReactNode }) => (
  <h2 className={`font-semibold leading-none tracking-tight ${className}`}>{children}</h2>
);

const CardDescription = ({ className = "", children }: { className?: string; children?: React.ReactNode }) => (
  children ? <p className={`mt-2 text-sm text-muted-foreground ${className}`}>{children}</p> : null
);

const CardContent = ({ className = "", children }: { className?: string; children: React.ReactNode }) => (
  <div className={`p-6 ${className}`}>{children}</div>
);

const CardFooter = ({ className = "", children }: { className?: string; children: React.ReactNode }) => (
  <div className={`flex items-center p-6 pt-0 ${className}`}>{children}</div>
);

export { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter };
