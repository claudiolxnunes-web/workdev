import { useCallback, useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import {
  approvePlan, getPlanRecommendation, getPlans, sendToBuild, subscribeToHandoffs,
  updatePlan, HandoffApiError, type AgentName, type ExecutionPlan,
  type PlanRecommendation,
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
  claude: "Claude Code", codex: "Codex", kimi: "Kimi Code", qwen: "Qwen Code", gemini: "Gemini",
}
// Os cinco agentes configurados. A recomendação nunca desabilita nenhum deles:
// o usuário pode ignorá-la e enviar para quem quiser.
const agents: Array<{ name: AgentName; className: string }> = [
  { name: "codex", className: "bg-sky-600 hover:bg-sky-500" },
  { name: "claude", className: "bg-violet-600 hover:bg-violet-500" },
  { name: "kimi", className: "bg-fuchsia-600 hover:bg-fuchsia-500" },
  { name: "qwen", className: "bg-amber-600 hover:bg-amber-500" },
  { name: "gemini", className: "bg-teal-600 hover:bg-teal-500" },
]
const costColor: Record<string, string> = {
  free: "text-emerald-300", economic: "text-emerald-300", moderate: "text-amber-300",
  premium: "text-rose-300", unknown: "text-slate-400",
}
const availabilityColor: Record<string, string> = {
  available: "text-emerald-300", unavailable: "text-rose-300", unknown: "text-slate-400",
}

function recommendationKey(plan: ExecutionPlan) {
  return `${plan.id}:${plan.updated_at}`
}

function RecommendationCard({
  recommendation, selectedModel, onSelectModel,
}: {
  recommendation: PlanRecommendation
  selectedModel?: string
  onSelectModel: (model: string) => void
}) {
  const { recommended, alternative } = recommendation
  // Só os modelos permitidos deste agente. O seletor aparece apenas quando há
  // mais de uma opção — com uma só, o modelo é informação, não escolha.
  const models = recommended.models ?? []
  const current = selectedModel ?? recommended.model ?? ""
  return (
    <section
      aria-label="Recomendação do WorkDev"
      className="mb-3 rounded-lg border border-slate-700 bg-slate-950/60 p-3 text-sm"
    >
      <p className="text-xs uppercase tracking-wide text-slate-500">Recomendação do WorkDev</p>
      <p className="mt-1 font-semibold text-slate-100">
        Recomendado: {recommended.agent_label}
      </p>
      <p className="text-xs text-slate-400">
        {recommended.model_label ?? "modelo não informado no catálogo"}
        {" · "}
        <span className={costColor[recommended.cost_class]}>custo {recommended.cost_label}</span>
        {" · "}
        complexidade {recommendation.complexity}
      </p>
      <p className="mt-1 text-slate-300">{recommended.reason}</p>
      {models.length > 1 && (
        <label className="mt-2 block text-xs text-slate-400">
          Modelo
          <select
            value={current}
            onChange={(event) => onSelectModel(event.target.value)}
            className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
          >
            {models.map((model) => (
              <option key={model.catalog_id ?? model.model} value={model.model ?? ""}>
                {model.model_label ?? model.model} · {model.cost_label}
                {model.recommended ? " · recomendado" : ""}
                {model.capable ? "" : " · abaixo do exigido"}
              </option>
            ))}
          </select>
        </label>
      )}
      <p className="mt-1 text-xs">
        <span className={availabilityColor[recommended.availability]}>
          Disponibilidade: {recommended.availability_label}
        </span>
        {" · "}
        <span className="text-slate-400">
          Disponibilidade financeira: {recommended.quota_label}
        </span>
      </p>
      {recommended.quota === "exhausted" && (
        <p className="mt-1 text-xs text-rose-300">
          Agente/modelo recomendado indisponível por cota/crédito.
        </p>
      )}
      {alternative && (
        <p className="mt-2 text-xs text-slate-400">
          Alternativa: <span className="text-slate-200">{alternative.agent_label}</span>
          {alternative.model_label ? ` (${alternative.model_label})` : ""} — {alternative.reason}
        </p>
      )}
      <p className="mt-2 text-xs text-slate-500">
        Sugestão consultiva: a escolha e o custo são decisão sua.
      </p>
    </section>
  )
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
  const [premiumTarget, setPremiumTarget] = useState<{
    plan: ExecutionPlan
    message: string
    model?: string
    agent?: AgentName
    requestedAgent?: AgentName
  } | null>(null)
  const [recommendations, setRecommendations] = useState<Record<string, PlanRecommendation>>({})
  // Modelo escolhido pelo usuário para aquele envio, por plano. Vazio = usa o
  // recomendado. A troca é consultiva e não altera nada no servidor.
  const [modelChoice, setModelChoice] = useState<Record<string, string>>({})
  const requestedRecommendations = useRef<Set<string>>(new Set())

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

  useEffect(() => {
    const pending = plans.filter(
      (plan) => !requestedRecommendations.current.has(recommendationKey(plan)),
    )
    if (pending.length === 0) return

    for (const plan of pending) {
      const key = recommendationKey(plan)
      requestedRecommendations.current.add(key)
      void getPlanRecommendation(plan.id)
        .then((recommendation) => {
          // A recomendação é consultiva: se falhar, a aba continua utilizável
          // e o usuário segue escolhendo o agente por conta própria.
          setRecommendations((current) => ({ ...current, [key]: recommendation }))
        })
        .catch(() => requestedRecommendations.current.delete(key))
    }
  }, [plans])

  async function approve(plan: ExecutionPlan) {
    setBusy(plan.id); setError(""); setMessage("")
    try { await approvePlan(plan.id); setMessage(`Plano v${plan.version} aprovado.`); await load() }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao aprovar") }
    finally { setBusy(null) }
  }

  function chosenModel(plan: ExecutionPlan, agent?: AgentName): string | undefined {
    const recommendation = recommendations[recommendationKey(plan)]
    const option = recommendation?.options?.find((item) => item.agent === agent)
    if (!option || option.models.length === 0) return undefined
    // A escolha do seletor só vale para o agente a que ela pertence; para os
    // demais botões vale o modelo recomendado daquele agente.
    const chosen = agent === recommendation?.recommended.agent
      ? modelChoice[plan.id]
      : undefined
    const valid = option.models.some((model) => model.model === chosen)
    if (valid) return chosen
    const recommended = option.models.find((model) => model.recommended)
    return recommended?.model ?? option.model ?? undefined
  }

  async function build(plan: ExecutionPlan, agent?: AgentName, premiumConfirmed = false) {
    setBusy(plan.id); setError(""); setMessage("")
    try {
      await sendToBuild(plan.id, agent, premiumConfirmed, chosenModel(plan, agent))
      setPremiumTarget(null)
      setMessage(agent ? `Build enviado para ${agentLabel[agent]}.` : "Build enviado.")
      await load()
    } catch (cause) {
      if (cause instanceof HandoffApiError && cause.detail.code === "premium_confirmation_required") {
        const recommended = cause.detail.details?.recommended
        setPremiumTarget({
          plan,
          message: cause.message,
          model: recommended?.model,
          agent: recommended?.agent,
          requestedAgent: agent,
        })
      } else {
        setError(cause instanceof Error ? cause.message : "Falha no handoff")
      }
    }
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
              {recommendations[recommendationKey(plan)] && (
                <RecommendationCard
                  recommendation={recommendations[recommendationKey(plan)]}
                  selectedModel={modelChoice[plan.id]}
                  onSelectModel={(model) =>
                    setModelChoice((current) => ({ ...current, [plan.id]: model }))
                  }
                />
              )}
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
                {plan.status === "approved" && agents.map(({ name, className }) => (
                  <button
                    key={name}
                    disabled={busy === plan.id}
                    onClick={() => void build(plan, name)}
                    className={`rounded-lg px-3 py-2 text-sm disabled:opacity-50 ${className}`}
                  >
                    Enviar ao {agentLabel[name]}
                  </button>
                ))}
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
        {premiumTarget && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-4" role="dialog" aria-modal="true" aria-labelledby="premium-title">
            <div className="w-full max-w-md rounded-xl border border-amber-800 bg-slate-950 p-5 shadow-2xl">
              <h3 id="premium-title" className="text-lg font-semibold">Autorizar modelo premium?</h3>
              <p className="mt-2 text-sm text-slate-300">{premiumTarget.message}</p>
              {premiumTarget.model && <p className="mt-3 text-sm text-amber-300">Recomendado: {premiumTarget.model}{premiumTarget.agent ? ` (${agentLabel[premiumTarget.agent]})` : ""}</p>}
              <p className="mt-2 text-xs text-slate-400">Esta confirmação autoriza somente o custo premium; o agente continua sendo o que você escolheu.</p>
              <div className="mt-5 flex justify-end gap-2">
                <button type="button" disabled={busy === premiumTarget.plan.id} onClick={() => setPremiumTarget(null)} className="rounded-lg bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700 disabled:opacity-50">Cancelar</button>
                <button type="button" disabled={busy === premiumTarget.plan.id} onClick={() => void build(premiumTarget.plan, premiumTarget.requestedAgent, true)} className="rounded-lg bg-amber-600 px-3 py-2 text-sm hover:bg-amber-500 disabled:opacity-50">Autorizar custo e continuar</button>
              </div>
            </div>
          </div>
        )}
      </aside>
    </div>
  )
}
