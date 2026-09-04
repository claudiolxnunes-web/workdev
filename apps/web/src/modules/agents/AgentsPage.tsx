import { useEffect, useState } from "react"
import { AgentTerminal } from "./AgentTerminal"
import type { OperationalStatus } from "./AgentTerminal"
import { BuildQueue } from "./BuildQueue"
import type { AgentName } from "@/services/handoff.service"

const AGENTS: Array<{ id: AgentName; label: string }> = [
  { id: "claude", label: "Claude Code" },
  { id: "codex", label: "Codex" },
  { id: "kimi", label: "Kimi Code" },
  { id: "qwen", label: "Qwen Code" },
  { id: "gemini", label: "Gemini" },
]

const STATUS_POLL_MS = 2000

type HealthStatus = "idle" | "busy" | "blocked" | "offline" | "degraded"
type AgentHealth = { health: HealthStatus; health_reason?: string | null; checked_at?: string | null }
type AgentOperation = { status: OperationalStatus; approvalPrompt?: string | null }

const OPERATION_LABEL: Record<OperationalStatus, string> = {
  standby: "STANDBY", executing: "EXECUTANDO", awaiting_approval: "AGUARDANDO APROVAÇÃO",
  awaiting_user: "AGUARDANDO USUÁRIO", completed: "CONCLUÍDO", blocked: "BLOQUEADO", error: "ERRO",
}

const OPERATION_STYLE: Record<OperationalStatus, string> = {
  standby: "bg-slate-700 text-slate-200", executing: "bg-sky-900 text-sky-200",
  awaiting_approval: "animate-pulse bg-amber-500 text-slate-950", awaiting_user: "bg-violet-900 text-violet-200",
  completed: "bg-emerald-900 text-emerald-200", blocked: "bg-orange-900 text-orange-200",
  error: "bg-red-900 text-red-200",
}

const HEALTH_STYLE: Record<HealthStatus, string> = {
  idle: "bg-emerald-400",
  busy: "bg-sky-400",
  degraded: "bg-amber-400",
  blocked: "bg-orange-500",
  offline: "bg-red-500",
}

const HEALTH_LABEL: Record<HealthStatus, string> = {
  idle: "Saudável e aguardando",
  busy: "Executando",
  degraded: "Operando com fallback",
  blocked: "Bloqueado",
  offline: "Offline",
}

type MobilePanel = "terminal" | "queue"

export default function AgentsPage() {
  const [agent, setAgent] = useState<AgentName>("claude")
  const [awaitingApproval, setAwaitingApproval] = useState<Partial<Record<AgentName, boolean>>>({})
  const [health, setHealth] = useState<Partial<Record<AgentName, AgentHealth>>>({})
  const [operations, setOperations] = useState<Partial<Record<AgentName, AgentOperation>>>({})
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("terminal")

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const response = await fetch("/api/agents/status")
        if (!response.ok) return
        const data = await response.json()
        if (cancelled || !Array.isArray(data.agents)) return
        const next: Partial<Record<AgentName, boolean>> = {}
        const nextHealth: Partial<Record<AgentName, AgentHealth>> = {}
        const nextOperations: Partial<Record<AgentName, AgentOperation>> = {}
        for (const item of data.agents) {
          const name = item.agent as AgentName
          next[name] = Boolean(item.awaiting_approval)
          nextHealth[name] = { health: item.health, health_reason: item.health_reason, checked_at: item.checked_at }
          nextOperations[name] = {
            status: item.operational_status as OperationalStatus,
            approvalPrompt: typeof item.approval_prompt === "string" ? item.approval_prompt : null,
          }
        }
        setAwaitingApproval(next)
        setHealth(nextHealth)
        setOperations(nextOperations)
      } catch { /* próxima rodada tenta de novo */ }
    }
    void poll()
    const interval = window.setInterval(poll, STATUS_POLL_MS)
    return () => { cancelled = true; window.clearInterval(interval) }
  }, [])

  return (
    <div className="flex min-h-[620px] min-w-0 max-w-full flex-col gap-3 overflow-hidden md:h-[calc(100dvh-9rem)] md:min-h-[420px]">
      <div className="flex min-w-0 flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div><h2 className="text-xl font-semibold sm:text-2xl">Agents</h2><p className="hidden text-sm text-slate-400 sm:block">Terminal seguro conectado às sessões tmux da VPS.</p></div>
        <div className="flex max-w-full overflow-x-auto rounded-lg border border-slate-700 bg-slate-900 p-1" role="tablist">
          {AGENTS.map((item) => (
            <button key={item.id} role="tab" aria-selected={agent === item.id} onClick={() => setAgent(item.id)}
              className={`relative min-h-10 shrink-0 rounded-md px-3 text-sm font-medium sm:px-4 ${agent === item.id ? "bg-sky-600 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
              {item.label}
              {health[item.id] && (
                <span
                  className={`ml-2 inline-block h-2 w-2 rounded-full ${HEALTH_STYLE[health[item.id]!.health]}`}
                  title={`${HEALTH_LABEL[health[item.id]!.health]}${health[item.id]!.health_reason ? `: ${health[item.id]!.health_reason}` : ""}`}
                />
              )}
              {awaitingApproval[item.id] && (
                <span className="ml-2 rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold text-slate-950">APROVAR</span>
              )}
            </button>
          ))}
        </div>
      </div>
      {health[agent] && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2 text-xs text-slate-300">
          <span className={`h-2.5 w-2.5 rounded-full ${HEALTH_STYLE[health[agent]!.health]}`} />
          <span className="font-medium">{HEALTH_LABEL[health[agent]!.health]}</span>
          {operations[agent] && <span className={`rounded px-2 py-1 font-bold ${OPERATION_STYLE[operations[agent]!.status]}`}>{OPERATION_LABEL[operations[agent]!.status]}</span>}
          {health[agent]!.health_reason && <span className="text-amber-300">Motivo: {health[agent]!.health_reason}</span>}
          {health[agent]!.checked_at && <span className="ml-auto text-slate-500">Última verificação: {new Date(health[agent]!.checked_at!).toLocaleTimeString("pt-BR")}</span>}
        </div>
      )}
      <div className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 p-1 md:hidden" role="tablist" aria-label="Painel">
        {(["terminal", "queue"] as MobilePanel[]).map((panel) => (
          <button key={panel} role="tab" aria-selected={mobilePanel === panel} onClick={() => setMobilePanel(panel)}
            className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium ${mobilePanel === panel ? "bg-sky-600 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
            {panel === "terminal" ? "Terminal" : "Fila de Build"}
          </button>
        ))}
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-hidden md:flex-row">
        <div className={mobilePanel === "queue" ? "flex min-h-0 flex-1 flex-col md:flex-none" : "hidden md:flex md:flex-none"}>
          <BuildQueue agent={agent} mobileExpanded={mobilePanel === "queue"} />
        </div>
        <div className={mobilePanel === "terminal" ? "flex min-h-0 min-w-0 flex-1 flex-col" : "hidden md:flex md:min-h-0 md:min-w-0 md:flex-1 md:flex-col"}>
          <AgentTerminal
            key={agent}
            agent={agent}
            awaitingApproval={Boolean(awaitingApproval[agent])}
            operationalStatus={operations[agent]?.status}
            approvalPrompt={operations[agent]?.approvalPrompt}
          />
        </div>
      </div>
    </div>
  )
}
