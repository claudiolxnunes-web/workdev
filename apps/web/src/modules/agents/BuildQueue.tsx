import { startTransition, useCallback, useEffect, useState } from "react"
import {
  getRunContext, getRuns, subscribeToHandoffs, transferRun, updateRun,
  updateRunSubtask, agentLabels, dispatchRun, HandoffApiError, RUNTIME_AGENTS,
  type AgentContext, type AgentName, type AgentRun, type DispatchJob,
  type RunStatus,
} from "@/services/handoff.service"

const statusLabel: Record<RunStatus, string> = {
  queued: "Aguardando", running: "Executando", blocked: "Bloqueado",
  review: "Revisão", completed: "Concluído", failed: "Falhou", cancelled: "Cancelado",
}
const statusColor: Record<RunStatus, string> = {
  queued: "text-amber-300", running: "text-sky-300", blocked: "text-red-300",
  review: "text-violet-300", completed: "text-emerald-300", failed: "text-red-300",
  cancelled: "text-slate-500",
}
const agentLabel = agentLabels

/** Um despacho já pedido não pode ser pedido de novo: o banco recusaria com
 *  409, e oferecer o botão assim mesmo seria convidar ao erro. */
const DESPACHO_EM_CURSO = ["queued", "dispatching"]

export function BuildQueue({ agent, mobileExpanded = false }: { agent: AgentName; mobileExpanded?: boolean }) {
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [context, setContext] = useState<AgentContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [copied, setCopied] = useState(false)
  const [job, setJob] = useState<DispatchJob | null>(null)

  const loadRuns = useCallback(async () => {
    try {
      const rows = await getRuns(agent)
      setRuns(rows)
      setSelectedId((current) => current && rows.some((run) => run.id === current)
        ? current : rows.find((run) => !["completed", "failed", "cancelled"].includes(run.status))?.id || rows[0]?.id || null)
      setError("")
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Erro na fila") }
    finally { setLoading(false) }
  }, [agent])

  const loadContext = useCallback(async (id: string) => {
    try { setContext(await getRunContext(id)); setError("") }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Erro no contexto") }
  }, [])

  useEffect(() => {
    startTransition(() => { setSelectedId(null); setContext(null); setLoading(true) })
    // loadRuns() é reaproveitado por 3 gatilhos (mount, evento realtime,
    // timer) — inline duplicaria a busca 3x; disable com escopo é mais
    // seguro que reestruturar um fluxo com subscription+interval.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadRuns()
    const unsubscribe = subscribeToHandoffs(() => void loadRuns())
    const timer = window.setInterval(() => void loadRuns(), 12000)
    return () => { unsubscribe(); window.clearInterval(timer) }
  }, [loadRuns])

  useEffect(() => {
    if (selectedId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void loadContext(selectedId)
    } else {
      startTransition(() => setContext(null))
    }
  }, [selectedId, loadContext])

  async function move(status: RunStatus) {
    if (!selectedId) return
    let message: string | undefined
    if (["blocked", "review", "completed", "failed", "cancelled"].includes(status)) {
      message = window.prompt(
        status === "blocked" ? "Qual é o bloqueio?"
          : status === "cancelled" ? "Motivo do cancelamento:"
          : status === "completed" ? "Resumo do resultado:" : "Resumo:",
      ) || undefined
      if (!message) return
    }
    setBusy(true); setError("")
    try {
      const fields: Record<string, string> = { status }
      if (message) fields.message = message
      if (status === "completed") { fields.result = message || "Build concluído"; fields.summary = message || "Build concluído" }
      if (["blocked", "failed"].includes(status) && message) fields.error = message
      if (["review", "cancelled"].includes(status) && message) fields.summary = message
      await updateRun(selectedId, fields)
      await Promise.all([loadRuns(), loadContext(selectedId)])
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao atualizar") }
    finally { setBusy(false) }
  }

  async function transfer() {
    if (!selectedId || !selected) return
    const others = (Object.keys(agentLabel) as AgentName[]).filter((name) => name !== selected.agent)
    const target = window.prompt(
      `Transferir para qual agente? (${others.join(", ")})`,
    )?.trim().toLowerCase()
    if (!target) return
    if (!others.includes(target as AgentName)) {
      setError(`Agente inválido. Use: ${others.join(", ")}`)
      return
    }
    const reason = window.prompt(
      "Motivo da transferência (ex.: créditos expiraram no meio da execução):",
    ) || undefined
    if (!reason) return
    setBusy(true); setError("")
    try {
      await transferRun(selectedId, target as AgentName, reason)
      setSelectedId(null)
      await loadRuns()
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao transferir") }
    finally { setBusy(false) }
  }

  async function toggleSubtask(id: string, current: string) {
    if (!selectedId) return
    const status = current === "done" ? "todo" : "done"
    setBusy(true)
    try { await updateRunSubtask(selectedId, id, status); await loadContext(selectedId) }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Falha na subtask") }
    finally { setBusy(false) }
  }

  /**
   * Pede o despacho da run para o runtime Ollama — a chamada que faltava e que
   * deixava a run parada para sempre depois de escolhida na tela de planos
   * (achado 1 do plano de correção).
   *
   * A resposta é 202: quando esta função retorna, o modelo ainda está
   * pensando. O resultado aparece no Histórico como `build.ollama_response`.
   */
  async function dispatch() {
    if (!selectedId) return
    setBusy(true); setError("")
    try {
      const resposta = await dispatchRun(selectedId)
      setJob(resposta.dispatch)
      await Promise.all([loadRuns(), loadContext(selectedId)])
    } catch (cause) {
      if (cause instanceof HandoffApiError
        && cause.detail.code === "dispatch_already_active") {
        // Não é erro do operador: já existe um despacho vivo. Mostramos qual.
        const vivo = cause.detail.details as DispatchJob | undefined
        if (vivo) setJob(vivo)
        setError("Já existe um despacho ativo para esta execução.")
      } else {
        setError(cause instanceof Error ? cause.message : "Falha ao despachar")
      }
    } finally { setBusy(false) }
  }

  async function copyPrompt() {
    if (!context) return
    try { await navigator.clipboard.writeText(context.prompt); setCopied(true); window.setTimeout(() => setCopied(false), 1800) }
    catch { setError("Não foi possível copiar; abra ‘Ver prompt completo’ e selecione o texto.") }
  }

  const selected = runs.find((run) => run.id === selectedId)
  return (
    <section className={`flex w-full shrink-0 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900 md:max-h-none md:w-80 ${mobileExpanded ? "min-h-0 flex-1" : "max-h-80"}`}>
      <div className="border-b border-slate-800 p-3">
        <h3 className="font-semibold">Fila de Build</h3>
        <p className="text-xs text-slate-500">Planos aprovados para {agentLabel[agent]}</p>
      </div>
      {error && <p className="m-3 rounded bg-red-950/50 p-2 text-xs text-red-300">{error}</p>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && <p className="p-3 text-sm text-slate-500">Carregando…</p>}
        {!loading && runs.length === 0 && <p className="p-4 text-sm text-slate-500">Nenhum Build enviado para este Agent.</p>}
        <div className="border-b border-slate-800">
          {runs.map((run) => <button key={run.id} onClick={() => setSelectedId(run.id)} className={`block w-full border-t border-slate-800/70 p-3 text-left hover:bg-slate-800 ${selectedId === run.id ? "bg-slate-800" : ""}`}>
            <p className="truncate text-sm font-medium">{run.task_title}</p>
            <div className="mt-1 flex justify-between text-xs"><span className="text-slate-500">v{run.plan_version} · {run.project_name}</span><span className={statusColor[run.status]}>{statusLabel[run.status]}</span></div>
          </button>)}
        </div>
        {selected && context && <div className="space-y-3 p-3 text-sm">
          <div><p className="text-xs font-medium uppercase tracking-wide text-slate-500">Objetivo</p><p className="mt-1 text-slate-300">{context.plan.objective}</p></div>
          <button onClick={() => void copyPrompt()} className="w-full rounded-lg bg-sky-600 px-3 py-2 font-medium hover:bg-sky-500">{copied ? "Contexto copiado" : "Copiar contexto para o Agent"}</button>
          <div className="flex flex-wrap gap-2">
            {selected.status === "queued" && <button disabled={busy} onClick={() => void move("running")} className="rounded bg-emerald-700 px-2 py-1 text-xs">Iniciar</button>}
            {selected.status === "blocked" && <button disabled={busy} onClick={() => void move("running")} className="rounded bg-sky-700 px-2 py-1 text-xs">Retomar</button>}
            {["running", "review"].includes(selected.status) && <button disabled={busy} onClick={() => void move("blocked")} className="rounded bg-red-800 px-2 py-1 text-xs">Bloquear</button>}
            {selected.status === "running" && <button disabled={busy} onClick={() => void move("review")} className="rounded bg-violet-700 px-2 py-1 text-xs">Enviar à revisão</button>}
            {["running", "review"].includes(selected.status) && <button disabled={busy} onClick={() => void move("completed")} className="rounded bg-emerald-700 px-2 py-1 text-xs">Concluir</button>}
            {["queued", "running", "blocked"].includes(selected.status) && <button disabled={busy} onClick={() => void transfer()} className="rounded bg-amber-700 px-2 py-1 text-xs" title="Cancela esta execução e cria uma nova para outro agente">Transferir</button>}
            {["queued", "running", "blocked"].includes(selected.status) && <button disabled={busy} onClick={() => void move("cancelled")} className="rounded bg-slate-700 px-2 py-1 text-xs">Cancelar</button>}
          </div>
          {RUNTIME_AGENTS.includes(selected.agent as typeof RUNTIME_AGENTS[number])
            && ["queued", "running"].includes(selected.status) && (
            <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-2">
              <button
                type="button"
                disabled={busy || DESPACHO_EM_CURSO.includes(selected.dispatch_state)}
                onClick={() => void dispatch()}
                className="w-full rounded bg-indigo-700 px-2 py-2 text-xs font-medium hover:bg-indigo-600 disabled:opacity-50"
              >
                {DESPACHO_EM_CURSO.includes(selected.dispatch_state)
                  ? "Despacho em curso…"
                  : "Despachar para o runtime"}
              </button>
              <p className="mt-2 text-[11px] text-amber-300">
                O runtime devolve texto. Ele não edita arquivo, não roda gate e
                não commita — a proposta chega no Histórico como
                build.ollama_response, para você aplicar.
              </p>
              {(job || selected.dispatch_attempts > 0) && (
                <p className="mt-1 text-[11px] text-slate-500">
                  Despacho: {job?.state ?? selected.dispatch_state}
                  {job?.model ? ` · ${job.model}` : ""}
                  {` · tentativa ${job?.attempt ?? selected.dispatch_attempts}`}
                  {job?.error ? ` · ${job.error}` : ""}
                </p>
              )}
            </div>
          )}
          {context.subtasks.length > 0 && <div><p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Subtasks</p>{context.subtasks.map((item) => <label key={item.id} className="flex cursor-pointer gap-2 py-1 text-xs text-slate-300"><input type="checkbox" disabled={busy} checked={item.status === "done"} onChange={() => void toggleSubtask(item.id, item.status)} /><span className={item.status === "done" ? "text-slate-500 line-through" : ""}>{item.order}. {item.title}</span></label>)}</div>}
          <details><summary className="cursor-pointer text-xs text-sky-400">Ver prompt completo</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-2 text-[11px] text-slate-400">{context.prompt}</pre></details>
          {context.events.length > 0 && <details><summary className="cursor-pointer text-xs text-slate-400">Histórico ({context.events.length})</summary><div className="mt-2 space-y-1">{context.events.slice().reverse().map((event) => <p key={event.id} className="text-[11px] text-slate-500"><span className="text-slate-300">{event.type}</span>{event.message ? ` · ${event.message}` : ""}</p>)}</div></details>}
        </div>}
      </div>
    </section>
  )
}
