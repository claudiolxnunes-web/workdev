import { useEffect, useMemo, useState } from "react"
import { AgentTerminal } from "./AgentTerminal"
import type { OperationalStatus } from "./AgentTerminal"
import { BuildQueue, type BuildQueueSummary } from "./BuildQueue"
import { RuntimeControls } from "./RuntimeControls"
import { RuntimePanel } from "./RuntimePanel"
import { ExecutorDefaults } from "./ExecutorDefaults"
import {
  getAgentRuntimes, type AgentName, type AgentRuntime, type RuntimeState, type ActivityState,
} from "@/services/handoff.service"

const AGENTS: Array<{ id: AgentName; label: string }> = [
  { id: "claude", label: "Claude Code" },
  { id: "codex", label: "Codex" },
  { id: "kimi", label: "Kimi Code" },
  { id: "qwen", label: "Qwen Code" },
  { id: "gemini", label: "Gemini" },
]

type AgentFilter = "todos" | "online" | "runtimes"

const FILTER_LABEL: Record<AgentFilter, string> = {
  todos: "Todos", online: "Online", runtimes: "Locais/GPU",
}

const RUNTIME_DOT: Record<string, string> = {
  online: "bg-emerald-400",
  degraded: "bg-red-500",
  offline: "bg-slate-500",
  unconfigured: "bg-slate-500",
}

const configuredStatusPollMs = Number(import.meta.env.VITE_AGENTS_STATUS_POLL_MS)
const STATUS_POLL_MS = Number.isFinite(configuredStatusPollMs)
  ? Math.min(10000, Math.max(5000, configuredStatusPollMs)) : 5000
const RUNTIME_POLL_MS = 10000

type HealthStatus = "idle" | "busy" | "blocked" | "offline" | "degraded"
type AgentHealth = { runtime_state?: RuntimeState; activity_state?: ActivityState; persistent?: boolean; health: HealthStatus; health_reason?: string | null; checked_at?: string | null }
type WorkspaceRun = { id: string; agent: AgentName; backlog_id: string; task_title: string; status: string }
type AgentOperation = { status: OperationalStatus }

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
  degraded: "bg-red-500",
  blocked: "bg-amber-400",
  offline: "bg-slate-500",
}

const HEALTH_LABEL: Record<HealthStatus, string> = {
  idle: "Saudável e aguardando",
  busy: "Executando",
  degraded: "Erro de runtime ou snapshot",
  blocked: "Atenção / bloqueado",
  offline: "Desligado",
}

type MobilePanel = "terminal" | "queue"

export default function AgentsPage() {
  const lastTerminalRun = localStorage.getItem("workdev_last_terminal_run")
  const [agent, setAgent] = useState<AgentName>("claude")
  const [selectedRuntimeId, setSelectedRuntimeId] = useState<string | null>(null)
  const [awaitingApproval, setAwaitingApproval] = useState<Partial<Record<AgentName, boolean>>>({})
  const [health, setHealth] = useState<Partial<Record<AgentName, AgentHealth>>>({})
  const [operations, setOperations] = useState<Partial<Record<AgentName, AgentOperation>>>({})
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("terminal")
  const [buildQueueOpen, setBuildQueueOpen] = useState(false)
  const [buildQueueSummary, setBuildQueueSummary] = useState<BuildQueueSummary | null>(null)
  const [runtimes, setRuntimes] = useState<AgentRuntime[]>([])
  const [workspaceRuns, setWorkspaceRuns] = useState<WorkspaceRun[]>([])
  const [stopPending, setStopPending] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')
  const [terminalOpen, setTerminalOpen] = useState(true)
  // Recolher é só visual: o AgentTerminal fica montado e o WebSocket vivo, então
  // a sessão continua recebendo saída enquanto a área está escondida. Diferente de
  // terminalOpen, que desconecta de fato.
  const [terminalCollapsed, setTerminalCollapsed] = useState(
    () => localStorage.getItem("workdev_terminal_collapsed") === "1",
  )
  const [filter, setFilter] = useState<AgentFilter>("todos")

  function toggleTerminalCollapsed() {
    setTerminalCollapsed(collapsed => {
      const proximo = !collapsed
      localStorage.setItem("workdev_terminal_collapsed", proximo ? "1" : "0")
      return proximo
    })
  }

  useEffect(() => {
    let cancelled = false
    let inFlight = false
    let timer: number | undefined
    let controller: AbortController | undefined
    const active = () => !cancelled && !document.hidden
    function schedule() {
      window.clearTimeout(timer)
      if (active()) timer = window.setTimeout(poll, STATUS_POLL_MS)
    }
    async function poll() {
      if (!active() || inFlight) return
      inFlight = true
      controller = new AbortController()
      try {
        const response = await fetch("/api/agents/status?workspace=true", { signal: controller.signal })
        if (!response.ok) throw new Error("Snapshot indisponível")
        const data = await response.json()
        if (cancelled) return
        if (!Array.isArray(data.agents)) throw new Error("Snapshot inválido")
        const next: Partial<Record<AgentName, boolean>> = {}
        const nextHealth: Partial<Record<AgentName, AgentHealth>> = {}
        const nextOperations: Partial<Record<AgentName, AgentOperation>> = {}
        for (const item of data.agents) {
          const name = item.agent as AgentName
          next[name] = Boolean(item.awaiting_approval)
          nextHealth[name] = { ...item, runtime_state: item.runtime_state ?? "ERROR", activity_state: item.activity_state ?? "IDLE" }
          nextOperations[name] = {
            status: item.operational_status as OperationalStatus,
          }
        }
        setWorkspaceRuns(data.agents.flatMap((row: { runs?: WorkspaceRun[] }) => row.runs ?? []))
        setAwaitingApproval(next)
        setHealth(nextHealth)
        setOperations(nextOperations)
      } catch (error) {
        if (!cancelled && !controller?.signal.aborted && !(error instanceof Error && error.name === 'AbortError')) {
          setHealth(Object.fromEntries(AGENTS.map(item => [item.id, { health: 'degraded', runtime_state: 'ERROR', activity_state: 'IDLE', health_reason: 'Snapshot indisponível' }])))
          setWorkspaceRuns([])
          setAwaitingApproval({})
          setOperations({})
        }
      }
      finally { inFlight = false; schedule() }
    }
    function visibilityChanged() {
      window.clearTimeout(timer)
      if (active()) schedule()
      else controller?.abort()
    }
    document.addEventListener("visibilitychange", visibilityChanged)
    const refresh = () => { void poll() }
    window.addEventListener("agent-runtime-refresh", refresh)
    void poll()
    return () => {
      window.removeEventListener("agent-runtime-refresh", refresh)
      cancelled = true
      window.clearTimeout(timer)
      controller?.abort()
      document.removeEventListener("visibilitychange", visibilityChanged)
    }
  }, [])

  useEffect(() => {
    // Runtimes Ollama são sondados pelo backend. Endpoint fora do ar volta
    // como estado, então a página nunca quebra por causa de uma GPU desligada.
    let cancelled = false
    async function poll() {
      try {
        const rows = await getAgentRuntimes()
        if (!cancelled) setRuntimes(rows)
      } catch {
        if (!cancelled) setRuntimes(previous => previous.map(row => ({ ...row, runtime_state: 'ERROR', activity_state: 'IDLE', status: 'offline', status_label: 'ERROR', reason: 'Snapshot indisponível', dispatchable: false, busy: false })))
      }
    }
    void poll()
    const interval = window.setInterval(poll, RUNTIME_POLL_MS)
    window.addEventListener('agent-runtime-refresh', poll)
    return () => { cancelled = true; window.clearInterval(interval); window.removeEventListener('agent-runtime-refresh', poll) }
  }, [])

  const selectedRuntime = selectedRuntimeId
    ? runtimes.find((runtime) => runtime.id === selectedRuntimeId)
    : undefined

  const visibleAgents = useMemo(() => {
    if (filter === "runtimes") return []
    if (filter === "online") {
      return AGENTS.filter((item) => {
        return health[item.id]?.runtime_state === "ONLINE"
      })
    }
    return AGENTS
  }, [filter, health])

  const visibleRuntimes = useMemo(() => {
    if (filter === "online") return runtimes.filter((item) => item.dispatchable)
    return runtimes
  }, [filter, runtimes])

  async function stopWorkspaceRun(run: WorkspaceRun) {
    if (!window.confirm(`Parar a Run ${run.id} de ${run.task_title}?`)) return
    setStopPending(run.id); setActionError('')
    try {
      const response = await fetch(`/api/handoffs/runs/${run.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'cancelled' }),
      })
      if (!response.ok) {
        const body = await response.json()
        throw new Error(body.detail?.message || 'Não foi possível confirmar a parada da Run')
      }
      setWorkspaceRuns(rows => rows.filter(row => row.id !== run.id))
      window.dispatchEvent(new Event('agent-runtime-refresh'))
    } catch (error) { setActionError(error instanceof Error ? error.message : 'Falha na parada') }
    finally { setStopPending(null) }
  }

  return (
    <div className="mx-auto flex w-full min-h-[620px] min-w-0 max-w-screen-2xl flex-col gap-2 overflow-hidden md:h-[calc(100dvh-9rem)] md:min-h-[420px]">
      <ExecutorDefaults />
      
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2"><div className="flex min-w-0 items-center gap-3">
        <div className="min-w-56 shrink-0"><h2 className="text-lg font-semibold sm:text-xl">Agent Workspace</h2><p className="hidden text-xs text-slate-400 lg:block">Agentes, execuções e terminais com estado real do runtime.</p></div>
          {lastTerminalRun && <a className="shrink-0 text-xs text-sky-400 hover:underline" href={`/runs/${encodeURIComponent(lastTerminalRun)}/terminal`}>Retomar terminal</a>}
        </div>
        <div className="flex gap-1 rounded-lg border border-slate-700 bg-slate-900 p-1" role="group" aria-label="Filtrar agentes">
          {(["todos", "online", "runtimes"] as AgentFilter[]).map((item) => (
            <button key={item} type="button" aria-pressed={filter === item} onClick={() => setFilter(item)}
              className={`rounded-md px-2 py-1 text-xs font-medium ${filter === item ? "bg-sky-600 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
              {FILTER_LABEL[item]}
            </button>
          ))}
        </div>
        <div className="flex w-full max-w-full overflow-x-auto rounded-lg border border-slate-700 bg-slate-900 p-1" role="tablist">
          {visibleRuntimes.map((item) => (
            <button key={item.id} role="tab" aria-selected={selectedRuntimeId === item.id} onClick={() => setSelectedRuntimeId(item.id)}
              className={`relative min-h-8 shrink-0 rounded-md px-2 text-xs font-medium sm:px-3 ${selectedRuntimeId === item.id ? "bg-sky-600 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
              {item.label}
              <span
                className={`ml-2 inline-block h-2 w-2 rounded-full ${RUNTIME_DOT[item.status] ?? "bg-slate-500"}`}
                title={`${item.status_label}${item.reason ? `: ${item.reason}` : ""}`}
              />
            </button>
          ))}
          {visibleAgents.map((item) => (
            <button key={item.id} role="tab" aria-selected={agent === item.id && selectedRuntimeId === null} onClick={() => { setAgent(item.id); setSelectedRuntimeId(null) }}
              className={`relative min-h-8 shrink-0 rounded-md px-2 text-xs font-medium sm:px-3 ${agent === item.id && selectedRuntimeId === null ? "bg-sky-600 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
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
      <section aria-label="Runs ativas" className="flex max-h-20 flex-nowrap gap-2 overflow-x-auto overflow-y-hidden">
        {workspaceRuns.filter(run => run.agent === agent).map(run => <div key={run.id} className="shrink-0 rounded border border-slate-700 px-2 py-1"><button
          type="button"
          onClick={() => window.open(
            `/runs/${encodeURIComponent(run.id)}/terminal?compact=1`,
            `workdev-run-${run.id}`,
            "width=920,height=680,resizable=yes,scrollbars=no"
          )}
          className="block rounded px-2 py-1 text-left text-xs hover:bg-slate-800">
          <strong>{run.task_title}</strong> · {run.status}
          <span className="block text-xs text-slate-400">{run.agent} · Run {run.id}</span>
          <span className="text-sky-400">Abrir terminal da execução</span>
        </button>
          {['queued', 'running', 'blocked'].includes(run.status) && <button
            disabled={stopPending !== null} onClick={() => void stopWorkspaceRun(run)}
            className="ml-2 rounded bg-red-950 px-2 py-1 text-sm">{stopPending === run.id ? 'Parando…' : 'Parar Run'}</button>}
        </div>)}
        {!workspaceRuns.some(run => run.agent === agent) && <span className="text-xs text-slate-400">Nenhuma Run ativa disponível neste snapshot.</span>}
      </section>
      {actionError && <p role="alert" className="text-red-300">{actionError}</p>}
      {!selectedRuntime && <button className="self-start rounded border border-slate-700 px-3 py-1 text-sm"
        onClick={() => setTerminalOpen(open => !open)}>{terminalOpen ? 'Fechar terminal do agente' : 'Abrir terminal do agente'}</button>}
      {!selectedRuntime && <RuntimeControls key={agent} agent={agent} runtimeState={health[agent]?.runtime_state} activityState={health[agent]?.activity_state} persistent={health[agent]?.persistent} checkedAt={health[agent]?.checked_at} />}
      {!selectedRuntime && health[agent] && (
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
      <div className="hidden items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-1.5 text-xs md:flex">
        <button
          type="button"
          onClick={() => setBuildQueueOpen(open => !open)}
          className="rounded bg-slate-800 px-2 py-1 text-sky-300 hover:bg-slate-700"
        >
          {buildQueueOpen ? "Ocultar fila" : "Abrir fila"}
        </button>
        {!selectedRuntime && (
          <button
            type="button"
            onClick={toggleTerminalCollapsed}
            aria-expanded={!terminalCollapsed}
            className="rounded bg-slate-800 px-2 py-1 text-sky-300 hover:bg-slate-700"
          >
            {terminalCollapsed ? "▸ Expandir terminal" : "▾ Recolher terminal"}
          </button>
        )}
        {terminalCollapsed && !selectedRuntime && (
          <span className="shrink-0 text-slate-400">
            Terminal recolhido — {agent} segue conectado
          </span>
        )}
        {buildQueueSummary ? (
          <>
            <span className="min-w-0 truncate font-medium text-slate-200">
              {buildQueueSummary.taskTitle}
            </span>
            <span className="shrink-0 text-sky-300">
              {buildQueueSummary.status}
            </span>
            <span className="shrink-0 text-slate-400">
              Subtasks {buildQueueSummary.done}/{buildQueueSummary.total}
            </span>
          </>
        ) : (
          <span className="text-slate-500">Nenhuma execução selecionada</span>
        )}
      </div>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 overflow-hidden md:flex-row">
        <div className={
          mobilePanel === "queue"
            ? "flex min-h-0 flex-1 flex-col md:flex-none"
            : buildQueueOpen
              ? "hidden md:flex md:flex-none"
              : "hidden"
        }>
          <BuildQueue agent={agent} mobileExpanded={mobilePanel === "queue"} onSummaryChange={setBuildQueueSummary} />
        </div>
        <div className={
          // `hidden` mantém o componente montado (só display:none), então o
          // ResizeObserver do AgentTerminal refaz o fit sozinho ao reexpandir.
          terminalCollapsed
            ? "hidden"
            : mobilePanel === "terminal"
              ? "flex min-h-0 min-w-0 flex-1 flex-col"
              : "hidden md:flex md:min-h-0 md:min-w-0 md:flex-1 md:flex-col"
        }>
          {selectedRuntime ? (
            // Runtime Ollama não tem sessão tmux: no lugar do terminal vai o
            // painel de estado operacional do endpoint.
            <RuntimePanel runtime={selectedRuntime} />
          ) : terminalOpen ? (
            <AgentTerminal
              key={agent}
              agent={agent}
              awaitingApproval={Boolean(awaitingApproval[agent])}
              operationalStatus={operations[agent]?.status}
            />
          ) : <p className="text-sm text-slate-400">Terminal desconectado. O agente continua em execução.</p>}
        </div>
      </div>
    </div>
  )
}
