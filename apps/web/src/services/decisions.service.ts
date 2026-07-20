const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export interface Decision {
  id: string;
  project_id: string;
  title: string;
  description: string;
  created_at: string;
}

export interface DecisionCreate {
  project_id: string;
  title: string;
  description: string;
}

export async function getDecisions(projectId?: string): Promise<Decision[]> {
  const qs = projectId ? `?project_id=${projectId}` : "";
  const response = await fetch(`/api/decisions${qs}`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar decisões");
  return response.json();
}

export async function createDecision(data: DecisionCreate): Promise<Decision> {
  const response = await fetch("/api/decisions", {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || "Erro ao criar decisão");
  }
  return response.json();
}
