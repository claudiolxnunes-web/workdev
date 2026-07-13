const API_URL = "";
  import.meta.env.VITE_API_URL ||
  "http://localhost:8000";
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
}

export async function getBacklog(): Promise<BacklogItem[]> {
  const response = await fetch(`${API_URL}/api/backlog`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar backlog");
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
