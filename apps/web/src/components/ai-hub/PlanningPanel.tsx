import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  approvePlan, getPlans, sendToBuild, subscribeToHandoffs, updatePlan,
  type AgentName, type ExecutionPlan,
} from "@/services/handoff.service"

const statusLabel: Record<string, string> = {
  draft: "Rascunho", approved: "Aprovado", needs_revision: "Revisar", superseded: "Substituído",
  discarded: "Descartado",
}
const statusColor: Record<string, string> = {
  draft: "bg-amber-500/20 text-amber-300", approved: "bg-emerald-500/20 text-emerald-300",
  needs_revision: "bg-red-500/20 text-red-300", superseded: "bg-slate-700 text-slate-400",
  discarded: "bg-slate-800 text-slate-300",
}
const agentLabel: Record<AgentName, string> = {
  claude: "Claude Code", codex: "Codex", kimi: "Kimi Code", qwen: "Qwen Code",
}

export function PlanningPanel({ onClose }: { onClose: () => void }) {
  const [plans, setPlans] = useState<ExecutionPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")
  const [filter, setFilter] = useState<"active" | "discarded">("active")
  const [editing, setEditing] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState("")
  const [editObjective, setEditObjective] = useState("")
  const [discardTarget, setDiscardTarget] = useState<ExecutionPlan | null>(null)

  const load = useCallback(async () => {
    try { setPlans(await getPlans(filter === "discarded" ? "discarded" : undefined)); setError("") }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Erro ao carregar planos") }
    finally { setLoading(false) }
  }, [filter])

  useEffect(() => {
    // load() é reaproveitado por 3 gatilhos (mount, evento realtime, timer)
    // e por approve() — inline duplicaria a busca 3x; disable com escopo é
    // mais seguro que reestruturar um fluxo com subscription+interval.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
    const unsubscribe = subscribeToHandoffs(() => void load())
    const timer = window.setInterval(() => void load(), 15000)
    return () => { unsubscribe(); window.clearInterval(timer) }
  }, [load])

  async function approve(plan: ExecutionPlan) {
    setBusy(plan.id); setError(""); setMessage("")
    try { await approvePlan(plan.id); setMessage(`Plano v${plan.version} aprovado.`); await load() }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao aprovar") }
    finally { setBusy(null) }
  }

  async function build(plan: ExecutionPlan, agent: AgentName) {
    setBusy(plan.id); setError(""); setMessage("")
    try {
      await sendToBuild(plan.id, agent)
      setMessage(`Build enviado para ${agentLabel[agent]}.`)
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha no handoff") }
    finally { setBusy(null) }
  }

  function beginEdit(plan: ExecutionPlan) {
    setEditing(plan.id); setEditTitle(plan.title); setEditObjective(plan.objective)
    setError(""); setMessage("")
  }

  async function saveEdit(plan: ExecutionPlan) {
    setBusy(plan.id); setError(""); setMessage("")
    try {
      await updatePlan(plan.id, { title: editTitle.trim(), objective: editObjective.trim() })
      setEditing(null); setMessage(`Plano v${plan.version} atualizado.`); await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao editar plano") }
    finally { setBusy(null) }
  }

  async function discard(plan: ExecutionPlan) {
    setBusy(plan.id); setError(""); setMessage("")
    try {
      await updatePlan(plan.id, { status: "discarded" })
      setDiscardTarget(null); setMessage(`Plano v${plan.version} descartado.`); await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao descartar plano") }
    finally { setBusy(null) }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/70" onClick={onClose}>
      <aside className="h-full w-full max-w-2xl overflow-y-auto border-l border-slate-700 bg-slate-950 p-4 sm:p-6" onClick={(event) => event.stopPropagation()}>
        <div className="mb-5 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold">Planos de execução</h2>
            <p className="text-sm text-slate-400">PLAN no AI Hub → aprovação → BUILD nos Agents</p>
          </div>
          <button className="text-xl text-slate-400 hover:text-white" onClick={onClose}>✕</button>
        </div>
        <div className="mb-4 flex gap-2" role="group" aria-label="Filtrar planos">
          <button type="button" onClick={() => setFilter("active")} className={`rounded-lg px-3 py-2 text-sm ${filter === "active" ? "bg-sky-600 text-white" : "bg-slate-900 text-slate-300"}`}>Fila ativa</button>
          <button type="button" onClick={() => setFilter("discarded")} className={`rounded-lg px-3 py-2 text-sm ${filter === "discarded" ? "bg-sky-600 text-white" : "bg-slate-900 text-slate-300"}`}>Descartados</button>
        </div>
        {message && <div className="mb-4 rounded-lg border border-emerald-800 bg-emerald-950/50 p-3 text-sm text-emerald-300">{message} <Link className="underline" to="/agents">Abrir Agents</Link></div>}
        {error && <div className="mb-4 rounded-lg border border-red-800 bg-red-950/50 p-3 text-sm text-red-300">{error}</div>}
        {loading && <p className="text-slate-400">Carregando…</p>}
        {!loading && plans.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-700 p-8 text-center text-sm text-slate-400">
            Ainda não há planos. Peça no chat: “crie um plano de execução para a task …”.
          </div>
        )}
        <div className="space-y-4">
          {plans.map((plan) => (
            <article key={plan.id} className="rounded-xl border border-slate-800 bg-slate-900 p-4">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                <div><p className="font-semibold">{plan.title}</p><p className="text-xs text-slate-500">{plan.task_title} · {plan.project_name} · plano v{plan.version}</p></div>
                <span className={`rounded-full px-2 py-1 text-xs ${statusColor[plan.status]}`}>{statusLabel[plan.status]}</span>
              </div>
              {editing === plan.id ? (
                <div className="mb-3 space-y-3">
                  <label className="block text-sm text-slate-300">Título
                    <input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" />
                  </label>
                  <label className="block text-sm text-slate-300">Objetivo
                    <textarea value={editObjective} onChange={(event) => setEditObjective(event.target.value)} rows={4} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" />
                  </label>
                </div>
              ) : <p className="mb-3 text-sm text-slate-300">{plan.objective}</p>}
              <details className="mb-3 text-sm text-slate-400">
                <summary className="cursor-pointer text-sky-400">Ver critérios e validações</summary>
                <div className="mt-2 space-y-3 border-l border-slate-700 pl-3">
                  <div><p className="font-medium text-slate-300">Critérios de aceite</p><ul className="list-disc pl-5">{plan.acceptance_criteria.map((item) => <li key={typeof item === "string" ? item : JSON.stringify(item)}>{typeof item === "string" ? item : (item as {item?: string}).item ?? JSON.stringify(item)}</li>)}</ul></div>
                  <div><p className="font-medium text-slate-300">Validações</p><ul className="list-disc pl-5">{plan.validation_steps.map((item) => <li key={typeof item === "string" ? item : JSON.stringify(item)}>{typeof item === "string" ? item : (item as {item?: string}).item ?? JSON.stringify(item)}</li>)}</ul></div>
                </div>
              </details>
              <div className="flex flex-wrap gap-2">
                {plan.status === "draft" && editing !== plan.id && <button disabled={busy === plan.id} onClick={() => beginEdit(plan)} className="rounded-lg bg-slate-700 px-3 py-2 text-sm hover:bg-slate-600 disabled:opacity-50">Editar</button>}
                {plan.status === "draft" && editing === plan.id && <>
                  <button disabled={busy === plan.id || editTitle.trim().length < 3 || editObjective.trim().length < 3} onClick={() => void saveEdit(plan)} className="rounded-lg bg-sky-600 px-3 py-2 text-sm hover:bg-sky-500 disabled:opacity-50">Salvar</button>
                  <button disabled={busy === plan.id} onClick={() => setEditing(null)} className="rounded-lg bg-slate-700 px-3 py-2 text-sm hover:bg-slate-600 disabled:opacity-50">Cancelar edição</button>
                </>}
                {["draft", "needs_revision"].includes(plan.status) && <button disabled={busy === plan.id} onClick={() => void approve(plan)} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm hover:bg-emerald-500 disabled:opacity-50">Aprovar plano</button>}
                {plan.status === "draft" && <button disabled={busy === plan.id} onClick={() => setDiscardTarget(plan)} className="rounded-lg border border-red-800 px-3 py-2 text-sm text-red-300 hover:bg-red-950 disabled:opacity-50">Descartar</button>}
                {plan.status === "approved" && <>
                  <button disabled={busy === plan.id} onClick={() => void build(plan, "codex")} className="rounded-lg bg-sky-600 px-3 py-2 text-sm hover:bg-sky-500 disabled:opacity-50">Enviar ao Codex</button>
                  <button disabled={busy === plan.id} onClick={() => void build(plan, "claude")} className="rounded-lg bg-violet-600 px-3 py-2 text-sm hover:bg-violet-500 disabled:opacity-50">Enviar ao Claude</button>
                  <button disabled={busy === plan.id} onClick={() => void build(plan, "kimi")} className="rounded-lg bg-fuchsia-600 px-3 py-2 text-sm hover:bg-fuchsia-500 disabled:opacity-50">Enviar ao Kimi</button>
                  <button disabled={busy === plan.id} onClick={() => void build(plan, "qwen")} className="rounded-lg bg-amber-600 px-3 py-2 text-sm hover:bg-amber-500 disabled:opacity-50">Enviar ao Qwen</button>
                </>}
              </div>
            </article>
          ))}
        </div>
        {discardTarget && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-4" role="dialog" aria-modal="true" aria-labelledby="discard-title">
            <div className="w-full max-w-md rounded-xl border border-red-900 bg-slate-950 p-5 shadow-2xl">
              <h3 id="discard-title" className="text-lg font-semibold">Descartar este plano?</h3>
              <p className="mt-2 text-sm text-slate-300">“{discardTarget.title}” sairá da fila ativa, mas continuará preservado no histórico de descartados.</p>
              <div className="mt-5 flex justify-end gap-2">
                <button type="button" disabled={busy === discardTarget.id} onClick={() => setDiscardTarget(null)} className="rounded-lg bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700 disabled:opacity-50">Voltar</button>
                <button type="button" disabled={busy === discardTarget.id} onClick={() => void discard(discardTarget)} className="rounded-lg bg-red-700 px-3 py-2 text-sm hover:bg-red-600 disabled:opacity-50">Confirmar descarte</button>
              </div>
            </div>
          </div>
        )}
      </aside>
    </div>
  )
}
