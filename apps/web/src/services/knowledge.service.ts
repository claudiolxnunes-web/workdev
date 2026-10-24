const API_URL = import.meta.env.VITE_API_URL || "";
const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export type KnowledgeCategory =
  | "decisao"
  | "licao"
  | "solucao"
  | "referencia"
  | "operacoes";

export interface KnowledgeEntry {
  id: string;
  title: string;
  content: string;
  category: KnowledgeCategory;
  tags: string | null;
  project_id: string | null;
  backlog_id: string | null;
  created_at: string;
}

export interface KnowledgeCreate {
  title: string;
  content: string;
  category: KnowledgeCategory;
  tags?: string;
  project_id?: string;
  backlog_id?: string;
}

export async function getKnowledge(
  categoria?: string,
  termo?: string,
  projectId?: string
): Promise<KnowledgeEntry[]> {
  const params = new URLSearchParams();
  if (categoria) params.set("categoria", categoria);
  if (termo) params.set("termo", termo);
  if (projectId) params.set("project_id", projectId);
  const qs = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_URL}/api/knowledge${qs}`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar conhecimento");
  return response.json();
}

export async function createKnowledge(
  data: KnowledgeCreate
): Promise<KnowledgeEntry> {
  const response = await fetch(`${API_URL}/api/knowledge`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string" ? detail : "Erro ao criar conhecimento"
    );
  }
  return response.json();
}
