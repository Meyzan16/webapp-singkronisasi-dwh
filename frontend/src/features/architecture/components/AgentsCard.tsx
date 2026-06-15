"use client";
import { Card, CardContent } from "@/components/ui/card";
import { AGENTS } from "../data";
import { Code, Badge, SectionTitle } from "./primitives";

interface Props {
  agentTab: string;
  setAgentTab: (t: string) => void;
}

export function AgentsCard({ agentTab, setAgentTab }: Props) {
  const activeAgent = AGENTS[agentTab as keyof typeof AGENTS];

  return (
    <Card>
      <CardContent className="pt-5">
        <SectionTitle icon="🤖" title="6 Autonomous Agents" sub="Berjalan 24/7 di background — embedded dalam FastAPI lifespan" />

        <div className="flex gap-2 mb-2 flex-wrap">
          <span className="text-[10px] font-black text-blue-500 uppercase tracking-widest">⚡ Futures:</span>
          {["Pre-Gainer", "Accumulation", "Momentum", "Futures Monitor", "Weight Updater"].map(t => (
            <button key={t} onClick={() => setAgentTab(t)}
              className={`text-[10px] px-2 py-0.5 rounded-full font-semibold transition-all ${
                agentTab === t ? "bg-blue-600 text-white" : "bg-blue-50 text-blue-600 hover:bg-blue-100"
              }`}>{t}</button>
          ))}
          <span className="text-[10px] font-black text-teal-600 uppercase tracking-widest ml-2">🎯 Spot:</span>
          {["Spot Opp Scanner", "Spot Monitor"].map(t => (
            <button key={t} onClick={() => setAgentTab(t)}
              className={`text-[10px] px-2 py-0.5 rounded-full font-semibold transition-all ${
                agentTab === t ? "bg-teal-600 text-white" : "bg-teal-50 text-teal-600 hover:bg-teal-100"
              }`}>{t}</button>
          ))}
        </div>

        {activeAgent && (
          <div className={`rounded-xl border bg-gradient-to-b p-4 mt-3 ${activeAgent.color}`}>
            <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
              <div className="flex items-center gap-3">
                <span className="text-3xl">{activeAgent.icon}</span>
                <div>
                  <p className="font-bold text-lg">{agentTab}</p>
                  <p className="text-xs text-neutral-500 font-mono">{activeAgent.file}</p>
                </div>
              </div>
              <div className="flex gap-2 flex-wrap">
                <Badge label={activeAgent.status}   color="bg-green-100 text-green-700" />
                <Badge label={activeAgent.interval} color="bg-neutral-100 text-neutral-600" />
                <Badge label={activeAgent.group}    color="bg-neutral-900 text-neutral-200" />
              </div>
            </div>

            <p className="text-sm text-neutral-700 mb-4 leading-relaxed">{activeAgent.desc}</p>

            <div className="grid md:grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-bold text-neutral-600 uppercase tracking-wider mb-2">Pipeline per Siklus</p>
                <div className="space-y-1.5">
                  {activeAgent.pipeline.map((step, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <span className="w-5 h-5 rounded-full bg-neutral-700 text-white text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5">
                        {i + 1}
                      </span>
                      <span className="text-neutral-600">{step}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-bold text-neutral-600 uppercase tracking-wider mb-2">Code Snippet</p>
                <Code>{activeAgent.code}</Code>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
