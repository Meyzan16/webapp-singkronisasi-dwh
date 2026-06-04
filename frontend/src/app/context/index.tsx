'use client';
import React, { createContext } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type AlertSeverity = "success" | "error" | "warning" | "info";

export interface AlertState {
  status: boolean;
  message: string;
  severity: AlertSeverity | "";
}

export interface CurrentUser {
  name: string;
  email: string;
  avatar?: string;
}

type ContextType = {
  openAlert: AlertState;
  setOpenAlert: React.Dispatch<React.SetStateAction<AlertState>>;
  pageLevelLoader: boolean;
  setPageLevelLoader: React.Dispatch<React.SetStateAction<boolean>>;
  currentUser: CurrentUser | null;
  setCurrentUser: React.Dispatch<React.SetStateAction<CurrentUser | null>>;
};

// ─── Context ──────────────────────────────────────────────────────────────────

export const GlobalContext = createContext<ContextType | null>(null);

export default function GlobalState({ children }: { children: React.ReactNode }) {
  const [openAlert, setOpenAlert] = React.useState<AlertState>({
    status: false,
    message: "",
    severity: "",
  });

  const [pageLevelLoader, setPageLevelLoader] = React.useState(false);

  const [currentUser, setCurrentUser] = React.useState<CurrentUser | null>(null);

  return (
    <GlobalContext.Provider
      value={{
        openAlert,
        setOpenAlert,
        pageLevelLoader,
        setPageLevelLoader,
        currentUser,
        setCurrentUser,
      }}
    >
      {children}
    </GlobalContext.Provider>
  );
}
