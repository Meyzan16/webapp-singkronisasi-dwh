// app/(dashboard)/client-shell.tsx
"use client";

import { useContext } from "react";
import { GlobalContext } from "../context";
import AlertComponent from "@/components/ui/alert";

export default function Client({ children }: { children: React.ReactNode }) {
  const { openAlert } = useContext(GlobalContext)!;

  return (
    <>
      {children}
      {openAlert.status && <AlertComponent />}
    </>
  );
}
