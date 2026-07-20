const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export type RFCStatus = "draft" | "review" | "accepted" | "rejected";

export interface RFC {
  id: string;
  project_id: string;
  title: string;
  context: string;
  proposal: string;
  consequences: string | null;
  status: RFCStatus;
  created_at: string;
  updated_at: string;
}

export interface RFCCreate {
  project_id: string;
  title: string;
  context: string;
  proposal: string;
  consequences?: string;
  status?: RFCStatus;
}

export async function getRFCs(projectId?: string): Promise<RFC[]> {
  const qs = projectId ? `?project_id=${projectId}` : "";
  const response = await fetch(`/api/rfcs${qs}`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar RFCs");
  return response.json();
}

export async function createRFC(data: RFCCreate): Promise<RFC> {
  const response = await fetch("/api/rfcs", {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || "Erro ao criar RFC");
  }
  return response.json();
}
