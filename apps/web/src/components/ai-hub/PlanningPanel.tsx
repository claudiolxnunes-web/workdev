import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  approvePlan, getPlans, sendToBuild, subscribeToHandoffs,
  type AgentName, type ExecutionPlan,
} from "@/services/handoff.service"

const statusLabel: Record<string, string> = {
  draft: "Rascunho", approved: "Aprovado", needs_revision: "Revisar", superseded: "Substituído",
}
const statusColor: Record<string, string> = {
  draft: "bg-amber-500/20 text-amber-300", approved: "bg-emerald-500/20 text-emerald-300",
  needs_revision: "bg-red-500/20 text-red-300", superseded: "bg-slate-700 text-slate-400",
}

export function PlanningPanel({ onClose }: { onClose: () => void }) {
  const [plans, setPlans] = useState<ExecutionPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")

  const load = useCallback(async () => {
    try { setPlans(await getPlans()); setError("") }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Erro ao carregar planos") }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
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
      setMessage(`Build enviado para ${agent === "codex" ? "Codex" : "Claude Code"}.`)
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha no handoff") }
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
                <div><p className="font-semibold">{plan.task_title}</p><p className="text-xs text-slate-500">{plan.project_name} · plano v{plan.version}</p></div>
                <span className={`rounded-full px-2 py-1 text-xs ${statusColor[plan.status]}`}>{statusLabel[plan.status]}</span>
              </div>
              <p className="mb-3 text-sm text-slate-300">{plan.objective}</p>
              <details className="mb-3 text-sm text-slate-400">
                <summary className="cursor-pointer text-sky-400">Ver critérios e validações</summary>
                <div className="mt-2 space-y-3 border-l border-slate-700 pl-3">
                  <div><p className="font-medium text-slate-300">Critérios de aceite</p><ul className="list-disc pl-5">{plan.acceptance_criteria.map((item) => <li key={item}>{item}</li>)}</ul></div>
                  <div><p className="font-medium text-slate-300">Validações</p><ul className="list-disc pl-5">{plan.validation_steps.map((item) => <li key={item}>{item}</li>)}</ul></div>
                </div>
              </details>
              <div className="flex flex-wrap gap-2">
                {["draft", "needs_revision"].includes(plan.status) && <button disabled={busy === plan.id} onClick={() => void approve(plan)} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm hover:bg-emerald-500 disabled:opacity-50">Aprovar plano</button>}
                {plan.status === "approved" && <>
                  <button disabled={busy === plan.id} onClick={() => void build(plan, "codex")} className="rounded-lg bg-sky-600 px-3 py-2 text-sm hover:bg-sky-500 disabled:opacity-50">Enviar ao Codex</button>
                  <button disabled={busy === plan.id} onClick={() => void build(plan, "claude")} className="rounded-lg bg-violet-600 px-3 py-2 text-sm hover:bg-violet-500 disabled:opacity-50">Enviar ao Claude</button>
                </>}
              </div>
            </article>
          ))}
        </div>
      </aside>
    </div>
  )
}
