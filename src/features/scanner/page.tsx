"use client";
import { ScannerDocs }   from "./components/ScannerDocs";
import { ScannerWidget } from "@/features/dashboard/components/ScannerWidget";

export default function ScannerPage() {
  return (
    <div className="space-y-6">
      <ScannerDocs />
      <ScannerWidget fullPage />
    </div>
  );
}
