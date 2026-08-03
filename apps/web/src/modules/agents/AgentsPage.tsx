import { useEffect, useState } from "react"
import { AgentTerminal } from "./AgentTerminal"
import { BuildQueue } from "./BuildQueue"
import type { AgentName } from "@/services/handoff.service"

const AGENTS: Array<{ id: AgentName; label: string }> = [
  { id: "claude", label: "Claude Code" },
  { id: "codex", label: "Codex" },
  { id: "kimi", label: "Kimi Code" },
  { id: "qwen", label: "Qwen Code" },
]

const STATUS_POLL_MS = 5000

export default function AgentsPage() {
  const [agent, setAgent] = useState<AgentName>("claude")
  const [awaitingApproval, setAwaitingApproval] = useState<Partial<Record<AgentName, boolean>>>({})

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const response = await fetch("/api/agents/status")
        if (!response.ok) return
        const data = await response.json()
        if (cancelled || !Array.isArray(data.agents)) return
        const next: Partial<Record<AgentName, boolean>> = {}
        for (const item of data.agents) next[item.agent as AgentName] = Boolean(item.awaiting_approval)
        setAwaitingApproval(next)
      } catch { /* próxima rodada tenta de novo */ }
    }
    void poll()
    const interval = window.setInterval(poll, STATUS_POLL_MS)
    return () => { cancelled = true; window.clearInterval(interval) }
  }, [])

  return (
    <div className="flex min-h-[620px] flex-col gap-3 md:h-[calc(100vh-8.5rem)] md:min-h-[420px]">
      <div className="flex items-center justify-between gap-3">
        <div><h2 className="text-xl font-semibold sm:text-2xl">Agents</h2><p className="hidden text-sm text-slate-400 sm:block">Terminal seguro conectado às sessões tmux da VPS.</p></div>
        <div className="flex flex-wrap rounded-lg border border-slate-700 bg-slate-900 p-1" role="tablist">
          {AGENTS.map((item) => (
            <button key={item.id} role="tab" aria-selected={agent === item.id} onClick={() => setAgent(item.id)}
              className={`relative min-h-10 rounded-md px-3 text-sm font-medium sm:px-4 ${agent === item.id ? "bg-sky-600 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
              {item.label}
              {awaitingApproval[item.id] && (
                <span
                  className="absolute -right-1 -top-1 h-2.5 w-2.5 animate-pulse rounded-full bg-amber-400"
                  title="Aguardando aprovação"
                />
              )}
            </button>
          ))}
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row">
        <BuildQueue agent={agent} />
        <AgentTerminal key={agent} agent={agent} awaitingApproval={Boolean(awaitingApproval[agent])} />
      </div>
    </div>
  )
}
