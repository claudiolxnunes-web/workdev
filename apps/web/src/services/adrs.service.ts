const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export type ADRStatus = "proposed" | "accepted" | "deprecated" | "superseded";

export interface ADR {
  id: string;
  project_id: string;
  feature_id: string | null;
  title: string;
  context: string;
  decision: string;
  consequences: string | null;
  status: ADRStatus;
  created_at: string;
  updated_at: string;
}

export interface ADRCreate {
  project_id: string;
  feature_id?: string;
  title: string;
  context: string;
  decision: string;
  consequences?: string;
  status?: ADRStatus;
}

export async function getADRs(projectId?: string): Promise<ADR[]> {
  const qs = projectId ? `?project_id=${projectId}` : "";
  const response = await fetch(`/api/adrs${qs}`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar ADRs");
  return response.json();
}

export async function createADR(data: ADRCreate): Promise<ADR> {
  const response = await fetch("/api/adrs", {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || "Erro ao criar ADR");
  }
  return response.json();
}
