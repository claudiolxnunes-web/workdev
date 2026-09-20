import { useParams } from "react-router-dom"
import { AgentTerminal } from "./AgentTerminal"
import { CLI_AGENTS, agentLabels, type AgentName } from "@/services/handoff.service"

/** Attach to the existing agent session; never create or restart an agent here. */
export default function AgentTerminalPage() {
  const { agentId } = useParams()
  if (!agentId || ![...CLI_AGENTS, "local-code"].includes(agentId)) {
    return <div className="p-6 text-slate-300">Agente sem terminal disponível. <a href="/agents" className="text-sky-300">Voltar aos agentes</a></div>
  }
  const agent = agentId as AgentName
  return <main className="flex h-dvh min-w-0 flex-col gap-2 bg-slate-950 p-2 text-white sm:p-3">
    <header className="flex shrink-0 items-center justify-between gap-2 text-sm">
      <h1 className="font-semibold">{agentLabels[agent]} · Terminal</h1>
      <a href="/agents" className="rounded px-3 py-2 text-sky-300 hover:bg-slate-800">Voltar aos agentes</a>
    </header>
    <AgentTerminal agent={agent} />
  </main>
}
