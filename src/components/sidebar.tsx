"use client";

import Image from "next/image"
import Link from "next/link"
import DottedSeparator from "./ui/dotted-separator"
import { Navigation } from "./navigation";
export const Sidebar = () => {
    return (
        <aside className="h-full flex flex-col p-2 w-full  bg-neutral-100 text-white justify-between">
                <Link className="px-4" href="/">
                    <Image src="/logo.svg" alt="logo" width={164} height={48} />
                </Link>
                <DottedSeparator className="my-4" />
                <Navigation />
        </aside>
    )
}