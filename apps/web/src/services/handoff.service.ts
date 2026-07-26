import { supabase } from "@/lib/supabase"

const API_KEY = import.meta.env.VITE_API_KEY || ""
const headers: HeadersInit = {
  "Content-Type": "application/json",
  "X-API-Key": API_KEY,
}

export type PlanStatus = "draft" | "approved" | "needs_revision" | "superseded"
export type RunStatus = "queued" | "running" | "blocked" | "review" | "completed" | "failed" | "cancelled"
export type AgentName = "codex" | "claude" | "kimi" | "qwen"

export interface ExecutionPlan {
  id: string
  backlog_id: string
  version: number
  status: PlanStatus
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

async function read<T>(responsePromise: Promise<Response>): Promise<T> {
  const response = await responsePromise
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || "Erro na integração PLAN → BUILD")
  return body as T
}

export async function getPlans(): Promise<ExecutionPlan[]> {
  return read(fetch("/api/handoffs/plans?limit=100", { headers }))
}

export async function approvePlan(id: string): Promise<ExecutionPlan> {
  return read(fetch(`/api/handoffs/plans/${id}/approve`, { method: "POST", headers }))
}

export async function sendToBuild(id: string, agent: AgentName): Promise<AgentRun> {
  return read(fetch(`/api/handoffs/plans/${id}/build`, {
    method: "POST", headers, body: JSON.stringify({ agent }),
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
