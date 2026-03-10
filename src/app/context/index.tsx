'use client';
import React, { createContext } from "react";

interface AlertState {
  status: boolean;
  message: string;
  severity: string;
};

interface ComponentLoaderState {
  loading: boolean;
  id: string;
};


type ContextType = {
  componentLevelLoader: ComponentLoaderState;
  setComponentLevelLoader: React.Dispatch<React.SetStateAction<ComponentLoaderState>>;
  pageLevelLoader: boolean;
  setPageLevelLoader: React.Dispatch<React.SetStateAction<boolean>>;
  openAlert: AlertState;
  setOpenAlert: React.Dispatch<React.SetStateAction<AlertState>>;

};

export const GlobalContext = createContext<ContextType | null>(null);

export default function GlobalState({
  children,
}: {
  children: React.ReactNode;
}) {

  const [openAlert, setOpenAlert] = React.useState<AlertState>({
    status: false,
    message: "",
    severity: "",
  });

  const [pageLevelLoader, setPageLevelLoader] = React.useState(false);

  const [componentLevelLoader, setComponentLevelLoader] = React.useState<ComponentLoaderState>({
    loading: false,
    id: "",
  });

  return (
    <GlobalContext.Provider
      value={{
        openAlert,
        setOpenAlert,
        pageLevelLoader,
        setPageLevelLoader,
        componentLevelLoader,
        setComponentLevelLoader
      }}
    >
      {children}
    </GlobalContext.Provider>
  );
}
