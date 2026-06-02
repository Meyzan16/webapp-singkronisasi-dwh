"use client";

import AlertComponent from "@/components/ui/alert";
import Image from "next/image";
import React, { useContext } from "react";
import { GlobalContext } from "../context";

interface AuthLayoutProps {
  children: React.ReactNode;
}

const AuthLayout = ({ children }: AuthLayoutProps) => {
  const { openAlert } = useContext(GlobalContext)!;

  return (
    <main className="bg-neutral-100 min-h-screen flex flex-col">
      <div className="mx-auto max-w-screen-2xl w-full p-6">
        <nav className="flex justify-between items-center">
          <Image src="/Danantara.png" height={60} width={152} alt="logo" />
          <div className="flex items-center gap-2">
            <Image src="/logo.svg" height={60} width={152} alt="logo" />
          </div>
        </nav>
      </div>
      <div className="flex-1 flex flex-col items-center justify-center px-6 font-sans min-h-[100svh] sm:min-h-[100dvh]">
        {children}
      </div>

      {openAlert.status == true && <AlertComponent />}
    </main>
  );
};

export default AuthLayout;
