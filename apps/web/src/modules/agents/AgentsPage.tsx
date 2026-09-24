import { useEffect, useState } from "react"
import { flushSync } from "react-dom"
import { AgentTerminal } from "./AgentTerminal"
import type { OperationalStatus } from "./AgentTerminal"
import { BuildQueue } from "./BuildQueue"
import { RuntimeControls } from "./RuntimeControls"
import { RuntimePanel } from "./RuntimePanel"
import { ExecutorDefaults } from "./ExecutorDefaults"
import { LocalModelSelector } from "./LocalModelSelector"
import { getAgentRuntimes, agentLabels, type AgentName, type AgentRuntime, type RuntimeState, type ActivityState } from "@/services/handoff.service"

const AGENTS: Array<{ id: AgentName; label: string }> = [
  { id: "claude", label: "Claude Code" }, { id: "codex", label: "Codex" },
  { id: "local-code", label: "Qwen 27B · Local" }, { id: "gemini", label: "Gemini" },
  { id: "kimi", label: "Kimi Code" }, { id: "qwen", label: "OpenRouter · Qwen CLI" },
]
const configuredStatusPollMs = Number(import.meta.env.VITE_AGENTS_STATUS_POLL_MS)
const STATUS_POLL_MS = Number.isFinite(configuredStatusPollMs) ? Math.min(10000, Math.max(5000, configuredStatusPollMs)) : 5000
const RUNTIME_POLL_MS = 10000
type AgentHealth = { runtime_state?: RuntimeState; activity_state?: ActivityState; persistent?: boolean; health: string; health_reason?: string | null; checked_at?: string | null }
type WorkspaceRun = { id: string; agent: AgentName; backlog_id: string; task_title: string; status: string }
type AgentOperation = { status: OperationalStatus }

export default function AgentsPage() {
  const [agent, setAgent] = useState<AgentName>(() => {
    const saved = sessionStorage.getItem("workdev_selected_agent")
    return AGENTS.find(item => item.id === saved)?.id ?? "claude"
  })
  const [awaitingApproval, setAwaitingApproval] = useState<Partial<Record<AgentName, boolean>>>({})
  const [health, setHealth] = useState<Partial<Record<AgentName, AgentHealth>>>({})
  const [operations, setOperations] = useState<Partial<Record<AgentName, AgentOperation>>>({})
  const [mobilePanel, setMobilePanel] = useState<"terminal" | "queue">("terminal")
  const [buildQueueOpen, setBuildQueueOpen] = useState(true)
  const [runtimes, setRuntimes] = useState<AgentRuntime[]>([])
  const [workspaceRuns, setWorkspaceRuns] = useState<WorkspaceRun[]>([])
  const [actionError, setActionError] = useState("")
  const [terminalOpen, setTerminalOpen] = useState(true)
  const [terminalCollapsed, setTerminalCollapsed] = useState(() => localStorage.getItem("workdev_terminal_collapsed") === "1")
  const [otherAgents, setOtherAgents] = useState(false)
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
      let timedOut = false
      const timeout = window.setTimeout(() => { timedOut = true; controller?.abort() }, 10000)
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
        if (!cancelled && (timedOut || (!controller?.signal.aborted && !(error instanceof Error && error.name === 'AbortError')))) {
          setHealth(Object.fromEntries(AGENTS.map(item => [item.id, { health: 'degraded', runtime_state: 'ERROR', activity_state: 'IDLE', health_reason: 'Snapshot indisponível' }])))
          setWorkspaceRuns([])
          setAwaitingApproval({})
          setOperations({})
        }
      }
      finally { window.clearTimeout(timeout); inFlight = false; schedule() }
    }
    function visibilityChanged() {
      window.clearTimeout(timer)
      if (active()) void poll()
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
    let inFlight = false
    async function poll() {
      if (cancelled || inFlight || document.hidden) return
      inFlight = true
      try {
        const rows = await getAgentRuntimes()
        if (!cancelled) setRuntimes(rows)
      } catch {
        if (!cancelled) setRuntimes(previous => previous.map(row => ({ ...row, runtime_state: 'ERROR', activity_state: 'IDLE', status: 'offline', status_label: 'ERROR', reason: 'Snapshot indisponível', dispatchable: false, busy: false })))
      } finally { inFlight = false }
    }
    void poll()
    const interval = window.setInterval(poll, RUNTIME_POLL_MS)
    window.addEventListener('agent-runtime-refresh', poll)
    return () => { cancelled = true; window.clearInterval(interval); window.removeEventListener('agent-runtime-refresh', poll) }
  }, [])


  const selectedRuntime = runtimes.find(row => row.id === agent)
  const remote = agent.startsWith("gpu-")
  const selectedHealth = health[agent] ?? selectedRuntime
  const state = selectedHealth?.runtime_state
  const activeRun = workspaceRuns.find(row => row.agent === agent && row.status === "running")
  const queuedRuns = workspaceRuns.filter(row => row.agent === agent && row.status === "queued")
  const choices = [...AGENTS, ...runtimes.filter(row => !AGENTS.some(item => item.id === row.id)).map(row => ({ id: row.id, label: row.label }))]

  function choose(id: AgentName) {
    setAgent(id)
    sessionStorage.setItem("workdev_selected_agent", id)
    setActionError("")
    setTerminalOpen(true)
  }
  function toggleTerminalCollapsed() {
    setTerminalCollapsed(value => {
      localStorage.setItem("workdev_terminal_collapsed", value ? "0" : "1")
      return !value
    })
  }
  function detachTerminal() {
    const tab = window.open("about:blank", "_blank")
    if (!tab) { setActionError("O navegador bloqueou a nova aba. Permita pop-ups para abrir o terminal."); return }
    tab.opener = null
    // Release this viewer before attaching the same persistent session elsewhere.
    flushSync(() => setTerminalOpen(false))
    tab.location.href = `/agents/${encodeURIComponent(agent)}/terminal`
    setActionError("")
  }

  return (
    <div className="mx-auto flex w-full min-w-0 max-w-screen-2xl flex-col gap-3 md:h-[calc(100dvh-6rem)] md:min-h-[520px]" data-testid="agent-workspace">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Agentes</h2>
        <div className="flex items-center gap-2 text-xs">
          <button className="hidden rounded border border-slate-700 px-3 py-2 hover:bg-slate-800 md:block" aria-expanded={buildQueueOpen} onClick={() => setBuildQueueOpen(value => !value)}>{buildQueueOpen ? "Ocultar tarefas" : "Mostrar tarefas"}</button>
          <button className="rounded border border-slate-700 px-3 py-2 hover:bg-slate-800" aria-expanded={otherAgents} onClick={() => setOtherAgents(value => !value)}>Runtimes remotos</button>
        </div>
      </header>
      <nav aria-label="Selecionar agente" className="flex shrink-0 flex-wrap gap-1 rounded-lg border border-slate-800 bg-slate-900 p-1" role="tablist">
        {choices.filter(item => otherAgents || AGENTS.some(primary => primary.id === item.id) || item.id === agent).map(item => {
          const current = health[item.id]?.runtime_state ?? runtimes.find(row => row.id === item.id)?.runtime_state
          return <button key={item.id} role="tab" aria-selected={agent === item.id} onClick={() => choose(item.id)} className={`flex min-h-10 shrink-0 items-center gap-2 rounded-md px-3 text-sm ${agent === item.id ? "bg-sky-700 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
            <span className={`h-2 w-2 rounded-full ${current === "ONLINE" ? "bg-emerald-400" : current === "ERROR" ? "bg-amber-400" : "bg-slate-500"}`} />
            {item.label}
            {awaitingApproval[item.id] && <span className="rounded bg-amber-400 px-1 text-[10px] font-bold text-slate-950">APROVAR</span>}
          </button>
        })}
      </nav>
      {agent === "qwen" && <p className="text-xs text-slate-400">OpenRouter está disponível nesta sessão do Qwen Code. Use /model no terminal para escolher o modelo e o provider.</p>}
      {agent === "local-code" && <LocalModelSelector />}
      <ExecutorDefaults />
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <RuntimeControls key={agent} agent={agent} runtimeState={state} activityState={selectedHealth?.activity_state} persistent={selectedHealth?.persistent} checkedAt={selectedHealth?.checked_at} />
        {!remote && <div className="flex flex-wrap gap-1 text-xs">
          <button onClick={detachTerminal} className="rounded bg-sky-950 px-3 py-2 text-sky-200 hover:bg-sky-900">Abrir em nova aba</button>
          <button className="hidden rounded px-3 py-2 text-slate-300 hover:bg-slate-800 md:block" aria-expanded={!terminalCollapsed} onClick={toggleTerminalCollapsed}>{terminalCollapsed ? "Expandir terminal" : "Recolher terminal"}</button>
          {!terminalOpen && <button className="rounded px-3 py-2 text-sky-300" onClick={() => { setTerminalOpen(true); setTerminalCollapsed(false) }}>Trazer terminal para cá</button>}
        </div>}
      </div>
      {queuedRuns.length > 0 && <p className="text-xs text-amber-300" role="status">QUEUED · {queuedRuns.length} tarefa(s) aguardando</p>}
      {actionError && <p role="alert" className="text-sm text-red-300">{actionError}</p>}
      {health[agent]?.health_reason && <details className="shrink-0 text-xs text-amber-300"><summary className="cursor-pointer">Detalhes do estado do agente</summary><p className="mt-1">{health[agent]?.health_reason}</p></details>}
      {activeRun && <div className="flex shrink-0 items-center gap-2 rounded-lg border border-sky-900 bg-sky-950/40 px-3 py-2 text-sm">
        <span className="shrink-0 text-sky-300">Em execução</span><strong className="min-w-0 flex-1 truncate">{activeRun.task_title}</strong>
        <a href={agent === "local-code" ? "/agents/local-code/terminal" : `/runs/${encodeURIComponent(activeRun.id)}/terminal?compact=1`} target="_blank" rel="noopener noreferrer" className="shrink-0 text-xs text-sky-300">Terminal da tarefa ↗</a>
      </div>}
      <div className="flex shrink-0 gap-1 rounded-lg bg-slate-900 p-1 md:hidden" role="tablist" aria-label="Painel">
        {(["terminal", "queue"] as const).map(panel => <button key={panel} role="tab" aria-selected={mobilePanel === panel} onClick={() => setMobilePanel(panel)} className={`min-h-10 flex-1 rounded text-sm ${mobilePanel === panel ? "bg-sky-700" : "text-slate-300"}`}>{panel === "terminal" ? "Terminal" : "Tarefas e subtarefas"}</button>)}
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 md:flex-row">
        <div className={`${mobilePanel === "queue" ? "flex" : "hidden"} ${buildQueueOpen ? "md:flex" : "md:hidden"} min-h-0 flex-col md:w-80 md:shrink-0`}>
          <BuildQueue key={agent} agent={agent} mobileExpanded={mobilePanel === "queue"} />
        </div>
        <div data-testid="terminal-panel" className={`${mobilePanel === "terminal" ? "flex" : "hidden"} ${terminalCollapsed && !remote ? "md:hidden" : "md:flex"} min-h-[480px] min-w-0 flex-1 flex-col md:min-h-0`}>
          {remote && selectedRuntime ? <RuntimePanel runtime={selectedRuntime} showControls={false} />
            : !terminalOpen ? <div className="rounded-lg border border-slate-800 p-6 text-sm text-slate-400">Terminal aberto em outra aba. Feche essa aba antes de trazê-lo para cá.</div>
            : state === "OFFLINE" ? <div className="rounded-lg border border-slate-800 p-6 text-sm text-slate-400">{agentLabels[agent]} está desligado. Use Ligar para iniciar e abrir o terminal.</div>
            : <AgentTerminal key={agent} agent={agent} awaitingApproval={Boolean(awaitingApproval[agent])} operationalStatus={operations[agent]?.status} />}
        </div>
        {terminalCollapsed && !remote && <button className="hidden self-start rounded border border-slate-800 px-4 py-3 text-sm text-sky-300 md:block" onClick={toggleTerminalCollapsed}>Terminal recolhido · Expandir</button>}
      </div>
    </div>
  )
}
