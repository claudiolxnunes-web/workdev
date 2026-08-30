import { supabase } from "@/lib/supabase"

const API_KEY = import.meta.env.VITE_API_KEY || ""
const headers: HeadersInit = {
  "Content-Type": "application/json",
  "X-API-Key": API_KEY,
}

export type PlanStatus = "draft" | "approved" | "needs_revision" | "superseded" | "discarded"
export type RunStatus = "queued" | "running" | "blocked" | "review" | "completed" | "failed" | "cancelled"
export type AgentName = "codex" | "claude" | "kimi" | "qwen" | "gemini"

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

export async function sendToBuild(
  id: string,
  agent?: AgentName,
  premiumConfirmed = false,
  model?: string,
): Promise<AgentRun> {
  const body = agent
    ? { routing_mode: "manual", agent, ...(model ? { model } : {}) }
    : { routing_mode: "auto", premium_confirmed: premiumConfirmed }

  return read(fetch(`/api/handoffs/plans/${id}/build`, {
    method: "POST", headers, body: JSON.stringify(body),
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
