const API_URL =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://localhost:8000" : "");
const API_KEY = import.meta.env.VITE_API_KEY || "";

const headers: HeadersInit = {
  "X-API-Key": API_KEY,
  "Content-Type": "application/json",
};

export interface BacklogItem {
  id: string;
  project_id: string;
  title: string;
  description?: string;
  type: string;
  priority: string;
  status: string;
  owner?: string;
  effort?: number;
  sprint?: string;
  rank?: number;
  created_at?: string;
  updated_at?: string;
}

export async function getBacklog(): Promise<BacklogItem[]> {
  const response = await fetch(`${API_URL}/api/backlog`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar backlog");
  return response.json();
}

export type BacklogEdit = Pick<BacklogItem, "title" | "description" | "priority" | "status">;

export async function updateItem(id: string, changes: Partial<BacklogEdit>): Promise<BacklogItem> {
  const response = await fetch(`${API_URL}/api/backlog/${encodeURIComponent(id)}`, {
    method: "PATCH", headers, body: JSON.stringify(changes),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    let message = `Erro ao salvar task (HTTP ${response.status})`;
    if (typeof detail === "string") message = detail;
    else if (typeof detail?.message === "string") message = detail.message;
    else if (Array.isArray(detail)) {
      const errors = detail.map(error => typeof error?.msg === "string" ? error.msg : "").filter(Boolean);
      if (errors.length) message = errors.join("; ");
    }
    throw new Error(message);
  }
  return response.json();
}

export async function updateStatus(id: string, status: string) {
  const response = await fetch(
    `${API_URL}/api/backlog/${id}/status?status=${status}`,
    { method: "PATCH", headers }
  );
  if (!response.ok) throw new Error("Erro ao atualizar status");
  return response.json();
}

export async function createItem(item: Partial<BacklogItem>) {
  const response = await fetch(`${API_URL}/api/backlog`, {
    method: "POST",
    headers,
    body: JSON.stringify(item),
  });
  if (!response.ok) throw new Error("Erro ao criar item");
  return response.json();
}

export async function deleteItem(id: string) {
  const response = await fetch(`/api/backlog/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error("Erro ao deletar item");
}

export interface Subtask {
  id: string;
  backlog_id: string;
  title: string;
  description?: string;
  status: string;
  execution_order: number;
  assigned_agent?: string;
  result?: string;
}

export async function getSubtasks(backlogId: string): Promise<Subtask[]> {
  const r = await fetch(`/api/subtasks/${backlogId}`);
  if (!r.ok) throw new Error("Erro ao buscar subtasks");
  return r.json();
}

export async function updateSubtask(id: string, data: Partial<Subtask>) {
  const r = await fetch(`/api/subtasks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!r.ok) throw new Error("Erro ao atualizar subtask");
  return r.json();
}

export interface TaskPlanningSession {
  id: string;
  task_id: string;
  task_title: string;
  project_slug: string;
  backlog_id: string;
}

export interface TaskPlanningEligibility {
  backlog_id: string;
  eligible: boolean;
  message: string | null;
  code: string | null;
}

export async function getTaskPlanningEligibility(taskId: string): Promise<TaskPlanningEligibility> {
  const response = await fetch(`/api/chat/sessions/from-task/${encodeURIComponent(taskId)}/eligibility`, { headers });
  if (!response.ok) throw new Error('Não foi possível verificar o planejamento desta task.');
  return response.json();
}

export async function createTaskPlanningSession(
  taskId: string
): Promise<TaskPlanningSession> {
  const response = await fetch("/api/chat/sessions/from-task", {
    method: "POST",
    headers,
    body: JSON.stringify({ task_id: taskId }),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const message = errorData.detail?.message || errorData.detail || "Erro ao enviar task ao AI Hub";
    throw new Error(message);
  }
  return response.json();
}
