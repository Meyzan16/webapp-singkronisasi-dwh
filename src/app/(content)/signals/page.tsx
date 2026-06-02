"use client";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function SignalsPage() {
  const [signals] = useState([]);
  return (
    <div className="space-y-6">
      <Card className="bg-gradient-to-r from-primarygreen to-teal-500 text-white border-0">
        <CardContent className="pt-6">
          <h1 className="text-3xl font-bold mb-2">Signal Feed</h1>
          <p className="text-sm opacity-90">Real-time trading signals with entry/exit levels and confidence scores</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <p className="text-muted-foreground">No signals available. Connect to backend API to fetch live signals.</p>
        </CardContent>
      </Card>
    </div>
  );
}
