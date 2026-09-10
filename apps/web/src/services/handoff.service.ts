import { supabase } from "@/lib/supabase"

const API_KEY = import.meta.env.VITE_API_KEY || ""
const headers: HeadersInit = {
  "Content-Type": "application/json",
  "X-API-Key": API_KEY,
}

export type PlanStatus = "draft" | "approved" | "needs_revision" | "superseded" | "discarded"
export type RunStatus = "queued" | "running" | "blocked" | "review" | "completed" | "failed" | "cancelled"
/** Agentes com CLI e sessão tmux própria na VPS. */
export type CliAgentName = "codex" | "claude" | "kimi" | "qwen" | "gemini"
/** Identidades de runtime Ollama — estáveis, independentes do modelo carregado. */
export type RuntimeAgentName = "local-code" | "gpu-hostinger" | "gpu-runpod"
export type AgentName = CliAgentName | RuntimeAgentName

export const CLI_AGENTS: CliAgentName[] = ["codex", "claude", "kimi", "qwen", "gemini"]
export const RUNTIME_AGENTS: RuntimeAgentName[] = ["local-code", "gpu-hostinger", "gpu-runpod"]

/**
 * Quem CONSEGUE emitir veredito. Espelha `AGENTS_WITH_REVIEW_CHANNEL` do
 * backend (`app/services/handoff.py`): capacidade implementada, não hierarquia
 * de qualidade. Só estes têm sessão tmux e a CLI `workdev_agent.py verdict`.
 */
export const AGENTS_WITH_REVIEW_CHANNEL: CliAgentName[] = [...CLI_AGENTS]

/**
 * Ordem de sugestão no seletor de revisor — dica visual, nunca filtro. A
 * escolha do executor e do revisor é sempre do operador, em todo envio.
 * `qwen` fica de fora por decisão dele (2026-09-09): é posicionado como
 * executor. Continua habilitado como revisor, só sem destaque.
 */
export const RECOMMENDED_REVIEWERS: CliAgentName[] = ["claude", "codex", "gemini", "kimi"]

export const agentLabels: Record<AgentName, string> = {
  claude: "Claude Code",
  codex: "Codex",
  kimi: "Kimi Code",
  qwen: "Qwen Code",
  gemini: "Gemini",
  "local-code": "Ollama local (VPS)",
  "gpu-hostinger": "GPU Hostinger",
  "gpu-runpod": "GPU RunPod",
}

export type RuntimeStatus = "online" | "offline" | "unconfigured" | "degraded"

export interface AgentRuntime {
  id: RuntimeAgentName
  label: string
  kind: "local" | "gpu"
  provider: string
  persistence: string
  auto_eligible: boolean
  configured: boolean
  model: string | null
  source_of_truth: boolean
  notes: string
  reprovision: { policy: string; steps: string[] }
  status: RuntimeStatus
  status_label: string
  reason: string | null
  models: string[]
  checked_at: string | null
  latency_ms: number | null
  dispatchable: boolean
  active_run_id: string | null
  busy: boolean
}

export type ReviewVerdict = "approved" | "rejected"

export interface RunReview {
  id: string
  run_id: string
  attempt: number
  executor_agent: AgentName
  reviewer_agent: AgentName
  verdict: ReviewVerdict
  feedback: string | null
  gate_passed: boolean | null
  created_at: string
}

export type CostClass = "free" | "economic" | "moderate" | "premium" | "unknown"
export type AvailabilityState = "available" | "unavailable" | "unknown"
export type QuotaState = "exhausted" | "unknown"
export type ComplexityLevel = "low" | "medium" | "high" | "critical"

export interface AgentModelOption {
  catalog_id: string | null
  model: string | null
  model_label: string | null
  provider: string | null
  category: string | null
  context_window: number | null
  capability_score: number
  capable: boolean
  missing_capabilities: string[]
  cost_class: CostClass
  cost_label: string
  price_index: string | null
  requires_confirmation: boolean
  preference_rank: number
  recommended: boolean
}

export interface AgentOption {
  agent: AgentName
  agent_label: string
  fit_score: string
  capable: boolean
  capability_score: number | null
  missing_capabilities: string[]
  catalog_id: string | null
  provider: string | null
  model: string | null
  model_label: string | null
  category: string | null
  context_window: number | null
  requires_confirmation: boolean
  cost_class: CostClass
  cost_label: string
  price_index: string | null
  availability: AvailabilityState
  availability_label: string
  availability_reason: string | null
  quota: QuotaState
  quota_label: string
  quota_reason: string | null
  reason: string
  /** Somente os modelos permitidos deste agente — nunca o catálogo inteiro. */
  models: AgentModelOption[]
}

export interface PlanRecommendation {
  plan_id: string
  plan_version: number
  complexity: ComplexityLevel
  complexity_score: number
  complexity_reason: string
  required_capabilities: string[]
  recommended: AgentOption
  alternative: AgentOption | null
  options: AgentOption[]
  runtime_checked: boolean
  pricing_source: string
}

export interface ExecutionPlan {
  id: string
  backlog_id: string
  version: number
  status: PlanStatus
  title: string
  objective: string
  scope?: string
  constraints: string[]
  acceptance_criteria: string[]
  validation_steps: string[]
  implementation_notes?: string
  created_by: string
  approved_at?: string
  created_at: string
  updated_at: string
  task_title: string
  project_id: string
  project_name: string
}

export interface AgentRun {
  id: string
  plan_id: string
  backlog_id: string
  agent: AgentName
  reviewer_agent: AgentName | null
  review_attempts: number
  status: RunStatus
  summary?: string
  result?: string
  error?: string
  branch?: string
  commit_sha?: string
  deployment_url?: string
  started_at?: string
  finished_at?: string
  created_at: string
  updated_at: string
  task_title: string
  project_id: string
  project_name: string
  plan_version: number
  /** Estado do despacho para runtime Ollama (fatia 2). Runs de agente com CLI
   *  ficam sempre em "idle": elas não passam por despacho, quem as executa é a
   *  sessão tmux. */
  dispatch_state: DispatchState
  dispatch_attempts: number
  last_dispatch_at?: string
}

export type DispatchState =
  | "idle" | "queued" | "dispatching" | "dispatched" | "failed"

export type DispatchJobState =
  | "queued" | "running" | "done" | "failed" | "cancelled"

export interface DispatchJob {
  job_id: string
  run_id: string
  runtime_id: RuntimeAgentName
  model: string | null
  state: DispatchJobState
  attempt: number
  prompt_sha256: string | null
  error: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  /** O que o modelo já gerou até agora. Cresce enquanto o job está vivo e é
   *  o que sobra se a geração morrer no meio. */
  partial_response: string
  partial_chars: number
  /** Resultado do build isolado (ADR 005), preenchido quando o envelope vira
   *  commit. Nulo enquanto o job só trocou texto: um job pode terminar sem
   *  produzir branch (envelope recusado), e a tela precisa distinguir os dois. */
  branch: string | null
  commit_sha: string | null
  gate_passed: boolean | null
  files: string[]
  diffstat: string | null
}

export interface AgentContext {
  run: { id: string; agent: AgentName; status: RunStatus; summary?: string; result?: string; error?: string }
  project: Record<string, string | null>
  task: Record<string, string | null>
  plan: ExecutionPlan
  subtasks: Array<{
    id: string
    order: number
    title: string
    description?: string
    status: "todo" | "doing" | "done"
    result?: string
  }>
  adrs: Array<{ id: string; title: string; decision: string; status: string }>
  knowledge: Array<{ id: string; title: string; category: string; content: string }>
  decisions: Array<{ id: string; title: string; description: string }>
  events: Array<{ id: string; type: string; message?: string; created_at?: string }>
  prompt: string
}

export interface HandoffErrorDetail {
  code?: string
  message: string
  details?: {
    recommended?: {
      model: string
      agent: AgentName
      capability_score: number
      category: string
    }
    [key: string]: unknown
  }
}

export class HandoffApiError extends Error {
  readonly detail: HandoffErrorDetail
  readonly status: number

  constructor(detail: HandoffErrorDetail, status: number) {
    super(detail.message)
    this.detail = detail
    this.status = status
    this.name = "HandoffApiError"
  }
}

async function read<T>(responsePromise: Promise<Response>): Promise<T> {
  const response = await responsePromise
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const raw = body.detail
    const detail: HandoffErrorDetail = typeof raw === "object" && raw !== null
      ? { ...raw, message: typeof raw.message === "string" ? raw.message : "Erro na integração PLAN → BUILD" }
      : { message: typeof raw === "string" ? raw : "Erro na integração PLAN → BUILD" }
    throw new HandoffApiError(detail, response.status)
  }
  return body as T
}

export async function getPlans(status?: PlanStatus): Promise<ExecutionPlan[]> {
  const query = new URLSearchParams({ limit: "100" })
  if (status) query.set("status", status)
  return read(fetch(`/api/handoffs/plans?${query}`, { headers }))
}

export async function updatePlan(
  id: string,
  data: { title?: string; objective?: string; status?: "discarded" },
): Promise<ExecutionPlan> {
  return read(fetch(`/api/plans/${id}`, {
    method: "PATCH", headers, body: JSON.stringify(data),
  }))
}

export async function approvePlan(id: string): Promise<ExecutionPlan> {
  return read(fetch(`/api/handoffs/plans/${id}/approve`, { method: "POST", headers }))
}

export async function getPlanRecommendation(id: string): Promise<PlanRecommendation> {
  return read(fetch(`/api/handoffs/plans/${id}/recommendation`, { headers }))
}

/**
 * Envia o plano ao Build. O revisor é obrigatório e precisa ser diferente do
 * executor — o backend recusa o par igual, isto aqui só evita a ida à rede.
 */
export async function sendToBuild(
  id: string,
  reviewer: AgentName,
  agent?: AgentName,
  premiumConfirmed = false,
  model?: string,
): Promise<AgentRun> {
  if (agent && agent === reviewer) {
    throw new HandoffApiError(
      { message: "Executor e revisor precisam ser agentes diferentes" },
      400,
    )
  }

  const body = agent
    ? { routing_mode: "manual", agent, reviewer, ...(model ? { model } : {}) }
    : { routing_mode: "auto", reviewer, premium_confirmed: premiumConfirmed }

  return read(fetch(`/api/handoffs/plans/${id}/build`, {
    method: "POST", headers, body: JSON.stringify(body),
  }))
}

export async function getAgentRuntimes(refresh = false): Promise<AgentRuntime[]> {
  const body = await read<{ runtimes: AgentRuntime[] }>(
    fetch(`/api/agent-runtimes${refresh ? "?refresh=true" : ""}`, { headers }),
  )
  return body.runtimes ?? []
}

/**
 * Pede o despacho da run para o runtime Ollama. Devolve 202 com o job — a
 * inferência NÃO acabou quando esta promise resolve.
 *
 * Chamada concorrente para a mesma run devolve 409 `dispatch_already_active`
 * com o job vivo em `detail.details`. Quem recusa é o índice parcial do banco,
 * não esta função: reapertar o botão não duplica inferência.
 */
export async function dispatchRun(runId: string): Promise<{
  run: AgentRun
  dispatch: DispatchJob
}> {
  return read(
    fetch(`/api/handoffs/runs/${runId}/dispatch`, { method: "POST", headers }),
  )
}

export async function getDispatchJob(
  runId: string,
  jobId: string,
): Promise<DispatchJob> {
  return read(
    fetch(`/api/handoffs/runs/${runId}/dispatch/${jobId}`, { headers }),
  )
}

export async function getRunReviews(runId: string): Promise<{
  run_id: string
  executor_agent: AgentName
  reviewer_agent: AgentName | null
  review_attempts: number
  reviews: RunReview[]
}> {
  return read(fetch(`/api/handoffs/runs/${runId}/reviews`, { headers }))
}

export async function submitRunReview(
  runId: string,
  reviewer: AgentName,
  verdict: ReviewVerdict,
  feedback?: string,
): Promise<{ review: RunReview; run: AgentRun }> {
  return read(fetch(`/api/handoffs/runs/${runId}/reviews`, {
    method: "POST", headers,
    body: JSON.stringify({ reviewer, verdict, feedback }),
  }))
}

export async function swapRunReviewer(
  runId: string,
  reviewer: AgentName,
  reason: string,
): Promise<AgentRun> {
  return read(fetch(`/api/handoffs/runs/${runId}/reviewer`, {
    method: "POST", headers, body: JSON.stringify({ reviewer, reason }),
  }))
}

export async function getRuns(agent?: AgentName): Promise<AgentRun[]> {
  const query = agent ? `?agent=${agent}&limit=100` : "?limit=100"
  return read(fetch(`/api/handoffs/runs${query}`, { headers }))
}

export async function getRunContext(id: string): Promise<AgentContext> {
  return read(fetch(`/api/handoffs/runs/${id}/context`, { headers }))
}

export async function updateRun(
  id: string,
  data: Partial<AgentRun> & { message?: string },
): Promise<AgentRun> {
  return read(fetch(`/api/handoffs/runs/${id}`, {
    method: "PATCH", headers, body: JSON.stringify(data),
  }))
}

export async function transferRun(
  id: string,
  agent: AgentName,
  reason: string,
): Promise<AgentRun> {
  return read(fetch(`/api/handoffs/runs/${id}/transfer`, {
    method: "POST", headers, body: JSON.stringify({ agent, reason }),
  }))
}

export async function updateRunSubtask(
  runId: string,
  subtaskId: string,
  status: "todo" | "doing" | "done",
  result?: string,
) {
  return read(fetch(`/api/handoffs/runs/${runId}/subtasks/${subtaskId}`, {
    method: "PATCH", headers, body: JSON.stringify({ status, result }),
  }))
}

export function subscribeToHandoffs(onChange: () => void): () => void {
  const channel = supabase
    .channel(`workdev-handoffs-${Math.random().toString(36).slice(2)}`)
    .on(
      "postgres_changes",
      { event: "*", schema: "public", table: "graph_nodes" },
      () => onChange(),
    )
    .subscribe()
  return () => { void supabase.removeChannel(channel) }
}
